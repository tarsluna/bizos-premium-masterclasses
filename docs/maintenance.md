# Maintenance des transcriptions

**Mise à jour :** le dépôt GitHub est privé. Un lecteur contrôlant l’abonnement a été déployé ; il attend son installation dans Whop. Le mode `reader_pending` maintient l’archive et le lecteur sans ajouter de nouveaux téléchargements Whop. Le fonctionnement historique décrit ci-dessous sera remplacé à l’activation de `member_reader` : voir [le guide du lecteur](lecteur-membres.md).

## Fonctionnement

La synchronisation lit uniquement l’expérience **Redif Call** du compte BizOS. Elle parcourt tous ses cours et leurs leçons visibles. Chaque leçon est identifiée par son identifiant Whop permanent.

La source privilégiée est le lien Fathom déjà présent dans la description. À défaut, le script récupère tous les segments des sous-titres français de la vidéo Whop/Mux. Les réponses brutes et les URL de lecture signées sont conservées exclusivement dans le dossier d’état local, hors du dépôt.

Pour privilégier Fathom sur une leçon existante, ajouter son lien de partage Fathom dans la description Whop, en dehors de la section générée. La synchronisation suivante détecte ce nouveau lien, remplace les sous-titres par la transcription Fathom et met à jour le fichier joint ainsi que GitHub. Plusieurs liens Fathom dans une même leçon provoquent une erreur explicite pour éviter de rattacher le mauvais appel. Le script n’invente aucune correspondance entre les appels privés du compte et les vidéos publiques.

Les transcriptions restent automatiques : des erreurs de reconnaissance et des répétitions peuvent exister dans la source, particulièrement dans les sous-titres Whop. Le texte n’est pas résumé ni réécrit. Les sous-titres identiques qui chevauchent deux segments réseau sont dédupliqués ; les autres paroles sont conservées. Des paragraphes de trente secondes améliorent la lecture sans retirer de texte.

## Description et fichiers Whop

Whop refuse les descriptions dépassant **65 000 caractères**. Chaque leçon reçoit donc :

- un fichier `.md` contenant l’intégralité de la transcription, téléchargeable sous la vidéo ;
- une section « Transcription intégrale » avec un lien vers la version lisible sur GitHub ;
- le texte complet directement dans la description lorsqu’il tient dans la limite.

Les liens, notes et pièces jointes déjà présents sont conservés. Seule la section délimitée par « Transcription intégrale » et « Fin de la transcription intégrale. » est gérée par le script. Les fichiers créés par une synchronisation précédente sont remplacés uniquement dans la liste des pièces jointes ; aucune vidéo n’est supprimée.

Avant chaque modification, le script relit la leçon et sauvegarde sa description et ses identifiants de pièces jointes. Après la modification, il relit Whop et vérifie le résultat. Les fichiers joints sont retéléchargés et comparés par SHA-256 avant leur rattachement.

## Configuration locale

Python 3.9 ou plus récent, Git et curl suffisent, sans dépendance Python externe.

Créer un fichier JSON **hors du dépôt**, accessible uniquement au compte local :

```json
{
  "state_dir": "/chemin/prive/bizos-masterclasses",
  "whop_env_file": "/chemin/prive/whop.env",
  "company_id": "biz_MIN8CMvS3er9z1",
  "experience_id": "exp_cwoa7S2imJmQVF",
  "github_repo": "tarsluna/bizos-premium-masterclasses",
  "github_token_file": "/chemin/prive/github-token"
}
```

Le fichier Whop doit définir `WHOP_API_KEY`. Le fichier GitHub contient uniquement le jeton. Aucun secret n’est placé dans les URL Git, les arguments des commandes Git ou le dépôt. Le jeton GitHub est fourni temporairement à Git par un assistant d’authentification limité à `github.com`.

Depuis la racine du dépôt :

```sh
# Préparer les Markdown et afficher les modifications prévues, sans écrire Whop/GitHub.
python3 -m scripts.sync --config /chemin/prive/config.json

# Mettre à jour Whop puis publier les Markdown sur GitHub.
python3 -m scripts.sync --config /chemin/prive/config.json --apply --publish

# Tests locaux, sans mutation de services externes.
python3 -m unittest discover -s tests -v
```

Le cache est lié à la vidéo et au lien Fathom. Supprimer seulement le fichier `cache/lesn_ID.transcript.json` du dossier d’état force la récupération de la transcription de cette leçon à la prochaine exécution.

## Tâche hebdomadaire sur macOS

L’installation locale utilise **launchd**, le planificateur macOS, chaque lundi à 09:00 dans le fuseau horaire du Mac. Il rattrape une échéance pendant la veille au réveil, selon la [documentation Apple](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html). Une extinction complète du Mac ne garantit pas un rattrapage : lancer alors la commande manuelle ci-dessus. Le compte utilisateur doit être connecté et le Mac doit avoir accès au réseau.

L’étiquette du service est `com.tarsluna.bizos-masterclasses`. Son fichier plist se trouve dans `~/Library/LaunchAgents/`. Les chemins propres à la machine et les secrets ne sont pas publiés dans ce dépôt.

Le script est protégé contre les exécutions concurrentes. Les résultats détaillés sont dans le dossier d’état : `last-run.json`, `last-failure.json`, `weekly.log` et `weekly.err`. Un code de sortie non nul signale une séance non traitée ou une erreur. Une transcription encore indisponible est réessayée au passage suivant et apparaît en attente dans le catalogue.

## Restaurer une description

Les fichiers `backups/lesn_ID-*.json` contiennent exactement les champs modifiés avant leur écriture. Après avoir choisi la sauvegarde et vérifié qu’elle correspond à la bonne leçon, envoyer uniquement ses champs `content` et `attachments` à `PATCH /api/v1/course_lessons/lesn_ID` avec la clé Whop. Désactiver d’abord la tâche planifiée si la restauration doit rester en place.

## API utilisées

- [Lister les cours Whop](https://docs.whop.com/api-reference/courses/list-courses)
- [Modifier une leçon Whop](https://docs.whop.com/api-reference/course-lessons/update-course-lesson)
- [Téléverser un fichier Whop](https://docs.whop.com/api-reference/files/create-file)
- [Sous-titres et transcriptions Mux](https://www.mux.com/docs/guides/add-autogenerated-captions-and-use-transcripts)

Fathom utilise les liens de partage déjà associés aux leçons et leur export de transcription. Si Fathom modifie ce format, le script conserve l’archive existante et signale l’erreur.
