# Lecteur réservé aux abonnés BizOS Premium

Le lecteur est déployé sur `https://bizos-premium-transcriptions.vercel.app`. Son application Whop est **BizOS Premium — Transcriptions**, identifiant `app_07aCN5rkbVTD00`.

**État : application créée, lecteur déployé, installation dans Whop encore nécessaire.** La clé de l’automatisation ne dispose pas de `app_authorization:create` : Whop refuse la création de l’expérience tant que l’application n’est pas installée. Arc affiche une page blanche dans l’outil de contrôle, ce qui empêche d’effectuer cette étape par l’interface et de valider le parcours connecté. Les descriptions et pièces jointes existantes ne sont pas encore migrées.

## Accès et fonctionnement

- Le serveur vérifie la signature ES256 du jeton Whop, son émetteur, son expiration et son audience exacte (cette application).
- Chaque chargement, lecture et clic sur **Tout copier** contrôle à nouveau l’abonnement via l’API Whop. Aucune autorisation positive n’est mise en cache.
- Un membre doit avoir un abonnement `active` au produit `prod_wC06oSFc928Lj` (BizOS YouTube / Premium), avec une période de validité future, une formule récurrente payante et une collecte des paiements non suspendue.
- Les essais, impayés, résiliations effectives et anciens accès gratuits sont refusés. Une résiliation en fin de période conserve l’accès jusqu’à cette échéance. Les administrateurs BizOS conservent l’accès.
- Une panne de Whop ferme l’accès. Le texte est effacé de l’interface en cas de refus lors du contrôle périodique (60 secondes) ou du retour sur la page.
- Les transcriptions sont exclusivement dans le bundle serveur, jamais dans les fichiers statiques ou le JavaScript du navigateur. Les réponses privées utilisent `no-store` et ne sont pas enregistrées dans le stockage local du navigateur.
- Le bouton copie le texte intégral. Si le navigateur refuse l’accès au presse-papiers dans l’iframe, le texte est sélectionné pour un simple ⌘C / Ctrl+C.

Un membre peut conserver et partager ce qu’il copie ou capture. Les fichiers déjà téléchargés ne peuvent pas être rappelés. Les liens Fathom des enregistrements préexistants gardent leurs propres règles de partage : leur révocation nécessite un accès Fathom et doit préserver les vidéos qui ne sont hébergées que là-bas.

## Activation dans Whop

1. Dans le tableau de bord développeur du compte BizOS, ouvrir **BizOS Premium — Transcriptions** et installer l’application dans BizOS. Elle ne demande aucune permission Whop supplémentaire (`requested_permissions: []`).
2. Récupérer l’expérience créée pour cette application, vérifier qu’elle appartient à `biz_MIN8CMvS3er9z1`, et la garder privée (`is_public: false`). La rattacher uniquement au produit Premium `prod_wC06oSFc928Lj`.
3. Dans le fichier de configuration **local privé**, remplacer `reader_pending` par `member_reader` et ajouter l’identifiant réel de l’expérience :

```json
"member_reader": {
  "app_id": "app_07aCN5rkbVTD00",
  "experience_id": "exp_IDENTIFIANT_REEL",
  "origin": "https://bizos-premium-transcriptions.vercel.app",
  "vercel_cli": "/chemin/absolu/vers/vercel"
}
```

4. Exécuter la synchronisation avec `--apply --publish`. Elle vérifie l’expérience, déploie le contenu serveur, puis remplace les sections générées par un lien Whop **Lire et copier la transcription**. Elle retire uniquement les fichiers Markdown qu’elle avait joints, conserve les vidéos et notes préexistantes, et vérifie les écritures.
5. Tester dans Whop avec un abonnement actif, un compte sans abonnement et un abonnement résilié. Le test connecté de bout en bout reste requis avant de déclarer la migration entièrement validée.

Un déploiement en échec empêche toute migration des liens Whop. Le GitHub reste une archive privée et n’est plus une destination de lecture des membres après activation.

## Synchronisation hebdomadaire

Avec `reader_pending`, le passage hebdomadaire continue l’archive privée et le déploiement du bundle protégé, sans ajouter de nouveaux fichiers téléchargeables dans Whop. Après activation de `member_reader`, il maintient également les liens de lecture protégée sous les vidéos. Le déploiement Vercel utilise la connexion locale existante ; aucune clé n’est passée sur la ligne de commande.

Les secrets Whop sont uniquement dans les variables serveur Vercel. `reader/data/` contient le bundle de transcription généré, ignoré par Git et inclus uniquement dans la fonction serveur. `reader/public/` contient seulement l’interface statique.

## Validation effectuée

- Tests de signature falsifiée, mauvaise audience, jeton expiré, contrôle d’abonnement et refus en cas de panne.
- Vérification réelle via Whop : abonnement actif accepté, abonnement résilié refusé, ancien accès gratuit refusé.
- Déploiement public : API sans identité refusée (401), aucun accès direct aux transcriptions, au code serveur ou aux variables d’environnement (404).
- Tests de migration : conservation des pièces jointes vidéo, retrait des seuls Markdown gérés, absence de doublons, aucun remplacement de lien si le déploiement échoue.

Sources : [authentification Whop](https://docs.whop.com/developer/guides/authentication), [vérification des accès](https://docs.whop.com/api-reference/beta/users/check-user-access), [app views](https://docs.whop.com/developer/guides/app-views). La vérification cryptographique utilise la clé publique et l’émetteur publiés dans le paquet officiel `@whop/api@0.0.51`, avec contrôle explicite de l’audience et de l’expiration.
