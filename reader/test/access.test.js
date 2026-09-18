import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPair, SignJWT } from 'jose';
import { verifyIdentity, authorizeMember, createHandler, configuration, whopApi } from '../lib/reader.js';

const cfg = {appId:'app_demo', companyId:'biz_demo', productId:'prod_premium', experienceId:'exp_reader', apiKey:'secret'};
const active = {user:{id:'user_member'}, company:{id:'biz_demo'}, product:{id:'prod_premium'}, plan:{id:'plan_paid'}, status:'active', renewal_period_end:'2099-01-01T00:00:00Z', payment_collection_paused:false};
const paid = {id:'plan_paid', product:{id:'prod_premium'}, plan_type:'renewal', renewal_price:249};
function apiFor(items, options={}) {
  return async path => {
    if(path.startsWith('users/')) return {has_access:true, access_level:options.admin?'admin':'customer'};
    if(path==='memberships') return {data:items, page_info:{has_next_page:false}};
    if(path.startsWith('plans/')) return {...paid,...options.plan};
    throw Error('unexpected route');
  };
}
test('JWT signature, audience, issuer and expiry are all mandatory', async()=>{
  const {publicKey,privateKey}=await generateKeyPair('ES256');
  const make=(aud='app_demo',iss='urn:whopcom:exp-proxy',exp='5m')=>new SignJWT({}).setProtectedHeader({alg:'ES256'}).setSubject('user_member').setAudience(aud).setIssuer(iss).setIssuedAt().setExpirationTime(exp).sign(privateKey);
  assert.equal(await verifyIdentity(await make(),cfg,publicKey),'user_member');
  for(const token of [await make('app_other'),await make('app_demo','wrong'),await make('app_demo','urn:whopcom:exp-proxy',1),'invalid']) {
    await assert.rejects(verifyIdentity(token,cfg,publicKey));
  }
  await assert.rejects(verifyIdentity('',cfg,publicKey));
  const other=await generateKeyPair('ES256');
  await assert.rejects(verifyIdentity(await make(),cfg,other.publicKey));
});
test('a paid active subscription grants access, including cancel-at-period-end', async()=>{
  for(const m of [active,{...active,cancel_at_period_end:true}]) assert.equal(await authorizeMember('user_member',cfg,apiFor([m])),true);
});
test('expired, canceled, trial, paused, free and unrelated memberships do not grant access', async()=>{
  for(const changes of [{status:'canceled'},{status:'trialing'},{status:'past_due'},{status:'completed'},{renewal_period_end:'2020-01-01'},{payment_collection_paused:true},{user:{id:'user_other'}},{product:{id:'prod_other'}},{company:{id:'biz_other'}}]) {
    assert.equal(await authorizeMember('user_member',cfg,apiFor([{...active,...changes}])),false);
  }
  assert.equal(await authorizeMember('user_member',cfg,apiFor([active],{plan:{renewal_price:0}})),false);
  assert.equal(await authorizeMember('user_member',cfg,apiFor([active],{plan:{plan_type:'one_time'}})),false);
  assert.equal(await authorizeMember('user_member',cfg,apiFor([])),false);
});
test('admins retain access, errors fail closed, and pagination is exhausted', async()=>{
  assert.equal(await authorizeMember('user_member',cfg,apiFor([],{admin:true})),true);
  await assert.rejects(authorizeMember('user_member',cfg,async()=>{throw Error('offline')}));
  const api=apiFor([active]); let pages=0;
  assert.equal(await authorizeMember('user_member',cfg,async(path,params)=>{
    if(path==='memberships' && pages++===0) return {data:[],page_info:{has_next_page:true,end_cursor:'next'}};
    if(path==='memberships') assert.equal(params.after,'next');
    return api(path);
  }),true);
});
function response(){return {headers:{},setHeader(k,v){this.headers[k]=v},end(body){this.body=body}}}
test('every transcript read rechecks access and no private text reaches denied clients',async()=>{
  let allowed=true,checks=0,loads=0;
  const handler=createHandler({config:()=>cfg,identity:async()=> 'user_member',authorize:async()=>{checks++;return allowed},load:async()=>{loads++;return [{id:'lesn_a',title:'Test',text:'SECRET TRANSCRIPT'}]}});
  const request={method:'GET',url:'/api/reader?lesson=lesn_a',headers:{}};
  const ok=response(); await handler(request,ok);
  assert.equal(ok.statusCode,200);assert.match(ok.body,/SECRET TRANSCRIPT/);
  assert.match(ok.headers['Cache-Control'],/no-store/);
  allowed=false; const denied=response();await handler(request,denied);
  assert.equal(denied.statusCode,403);assert.doesNotMatch(denied.body,/SECRET TRANSCRIPT/);assert.equal(checks,2);assert.equal(loads,1);
});
test('catalogue omits text; forged identity, missing lesson, wrong method and outage are safe',async()=>{
  const deps={config:()=>cfg,identity:async()=> 'user_member',authorize:async()=>true,load:async()=>[{id:'lesn_a',title:'Test',text:'SECRET'}]};
  for(const [request,change,status] of [
    [{method:'GET',url:'/api/reader',headers:{}},{},200],
    [{method:'GET',url:'/api/reader?lesson=bad',headers:{}},{},404],
    [{method:'POST',url:'/api/reader',headers:{}},{},405],
    [{method:'GET',url:'/api/reader',headers:{}},{identity:async()=>{throw Error('bad token')}},401],
    [{method:'GET',url:'/api/reader',headers:{}},{authorize:async()=>{throw Error('unavailable')}},503]
  ]) {const res=response();await createHandler({...deps,...change})(request,res);assert.equal(res.statusCode,status);assert.doesNotMatch(res.body,/SECRET/);}
});

test('configuration is mandatory and API calls remain on Whop with server-only authentication',async()=>{
  const keys=['WHOP_APP_ID','WHOP_COMPANY_ID','WHOP_PREMIUM_PRODUCT_ID','WHOP_API_KEY'];
  const original=keys.map(k=>process.env[k]);
  try {
    keys.forEach(k=>delete process.env[k]);assert.throws(configuration);
    keys.forEach((k,i)=>process.env[k]=[cfg.appId,cfg.companyId,cfg.productId,cfg.apiKey][i]);
    assert.deepEqual(configuration(),{appId:cfg.appId,companyId:cfg.companyId,productId:cfg.productId,apiKey:cfg.apiKey});
  }finally{keys.forEach((k,i)=>original[i]===undefined?delete process.env[k]:process.env[k]=original[i])}
  const old=globalThis.fetch;
  try {
    globalThis.fetch=async(url,options)=>{
      assert.equal(url.origin,'https://api.whop.com');
      assert.equal(url.searchParams.get('user_ids[]'),'user_member');
      assert.equal(options.headers.Authorization,'Bearer secret');
      assert.equal(options.cache,'no-store');
      return {ok:true,json:async()=>({data:[]})};
    };
    assert.deepEqual(await whopApi(cfg)('memberships',{'user_ids[]':'user_member'}),{data:[]});
    globalThis.fetch=async()=>({ok:false});await assert.rejects(whopApi(cfg)('memberships'));
  }finally{globalThis.fetch=old}
});
