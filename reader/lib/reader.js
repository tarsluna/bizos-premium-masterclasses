import { importJWK, jwtVerify } from 'jose';

// Public ES256 verification key published by Whop in @whop/api 0.0.51.
const whopKey = importJWK({kty:'EC', x:'rz8a8vxvexHC0TLT91g7llOdDOsNuYiGEfic4Qhni-E', y:'zH0QblKYToexd5PEIMGXPVJS9AB5smKrW4S_TbiXrOs', crv:'P-256'}, 'ES256');

export function configuration() {
  const cfg={appId:process.env.WHOP_APP_ID,companyId:process.env.WHOP_COMPANY_ID,
    productId:process.env.WHOP_PREMIUM_PRODUCT_ID,apiKey:process.env.WHOP_API_KEY};
  if(Object.values(cfg).some(x=>!x)) throw Error('Configuration missing');
  return cfg;
}

export async function verifyIdentity(token, config, key) {
  if(typeof token!=='string' || !token || !config.appId) throw Error('Identity required');
  const {payload}=await jwtVerify(token,key || await whopKey,{algorithms:['ES256'],issuer:'urn:whopcom:exp-proxy',audience:config.appId,requiredClaims:['sub','exp','aud','iss']});
  if(!/^user_[A-Za-z0-9]+$/.test(payload.sub) || payload.aud!==config.appId) throw Error('Invalid identity');
  return payload.sub;
}

export function whopApi(config) {
  return async(path,params={})=>{
    const url=new URL('https://api.whop.com/api/v1/'+path);
    for(const [key,value] of Object.entries(params))url.searchParams.set(key,String(value));
    const res=await fetch(url,{headers:{Authorization:'Bearer '+config.apiKey,Accept:'application/json'},cache:'no-store',signal:AbortSignal.timeout(12000)});
    if(!res.ok)throw Error('Whop unavailable');
    return res.json();
  };
}

export async function authorizeMember(userId,config,api=whopApi(config),now=Date.now()) {
  let after;const seen=new Set();
  do {
    const page=await api('memberships',{company_id:config.companyId,'product_ids[]':config.productId,'user_ids[]':userId,first:100,...(after?{after}:{})});
    for(const m of page.data) {
      if(m.user?.id!==userId || m.company?.id!==config.companyId || m.product?.id!==config.productId || m.status!=='active' || m.payment_collection_paused || !(Date.parse(m.renewal_period_end)>now))continue;
      const p=await api('plans/'+m.plan.id);
      if(p.product?.id===config.productId && p.plan_type==='renewal' && Number(p.renewal_price)>0)return true;
    }
    if(!page.page_info?.has_next_page)break;
    after=page.page_info.end_cursor;
    if(!after || seen.has(after))throw Error('Invalid pagination');
    seen.add(after);
  } while(true);
  const access=await api(`users/${userId}/access/${config.companyId}`);
  return Boolean(access.has_access && access.access_level==='admin');
}

export function createHandler({config=configuration,identity=verifyIdentity,authorize=authorizeMember,load}={}) {
  return async(req,res)=>{
    res.setHeader('Cache-Control','private, no-store, max-age=0');
    res.setHeader('CDN-Cache-Control','no-store');
    res.setHeader('Vercel-CDN-Cache-Control','no-store');
    res.setHeader('Vary','x-whop-user-token');
    res.setHeader('Content-Type','application/json; charset=utf-8');
    res.setHeader('X-Content-Type-Options','nosniff');
    const reply=(status,value)=>{res.statusCode=status;res.end(JSON.stringify(value))};
    if(req.method!=='GET'){res.setHeader('Allow','GET');return reply(405,{error:'Méthode non autorisée.'})}
    let cfg;try{cfg=config()}catch{return reply(503,{error:'Le lecteur est momentanément indisponible.'})}
    let userId;try{userId=await identity(req.headers['x-whop-user-token'],cfg)}catch{return reply(401,{error:'Ouvre ce lecteur depuis BizOS Premium sur Whop.'})}
    try {
      if(!await authorize(userId,cfg))return reply(403,{error:'Un abonnement BizOS Premium payant et actif est nécessaire.'});
      const query=new URL(req.url,'https://reader.invalid').searchParams;
      if(query.has('check'))return reply(200,{active:true});
      const catalogue=await load();
      const id=query.get('lesson');
      if(id) {
        const entry=catalogue.find(x=>x.id===id);
        return entry?reply(200,entry):reply(404,{error:'Transcription introuvable.'});
      }
      return reply(200,{lessons:catalogue.map(({text,...entry})=>entry)});
    } catch {return reply(503,{error:'La vérification de ton abonnement est momentanément indisponible. Réessaie dans un instant.'})}
  };
}
