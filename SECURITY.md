# Sécurité

## Modèle de menace

Le serveur est conçu pour **un seul utilisateur, derrière un VPN** (Tailscale ou WireGuard). Il ne doit jamais être exposé directement sur internet : le port n'est publié que sur la boucle locale, et c'est `tailscale serve` qui le rend joignable en HTTPS sur le réseau privé. Le mot de passe optionnel (`AC_MOT_DE_PASSE`) est une seconde barrière, pas un substitut au VPN.

Garde-fous en place :

- Le LLM n'a ni shell ni outil d'écriture (`Write`, `Edit`, `Bash` retirés et refusés). Ses lectures sont bornées à `agent/` et `recettes/`, que le moteur soit le CLI ou l'API : avec l'API, c'est le serveur qui exécute les lectures et contrôle chaque chemin (liens symboliques et fichiers cachés compris).
- Avec le moteur `openai`, c'est le serveur qui télécharge les pages demandées par le modèle : seules les adresses http(s) vers un hôte public sont acceptées, jamais une adresse locale ou privée.
- Aucun fichier n'est écrit sans validation manuelle dans l'interface. Les chemins proposés sont contrôlés (pas de `..`, pas de fichier caché, extension imposée).
- Le contenu des pages web lues par l'assistant est traité comme non fiable ; l'absence d'écriture et la validation manuelle bornent l'effet d'une injection d'instructions.
- Le HTML rendu dans l'interface est assaini (DOMPurify).
- Les liens ajoutés à la base documentaire doivent pointer vers un hôte public : les adresses locales et privées sont refusées.
- Les secrets (jeton Claude, clé de déploiement, configuration rclone) vivent hors dépôt, en lecture seule pour le service, et ne sont renvoyés par aucune route.

## Signaler une vulnérabilité

Merci de ne pas ouvrir d'issue publique. Utilise le [signalement privé de GitHub](https://github.com/MrLouix/Cooklang_server/security/advisories/new) en décrivant le scénario, la version (commit) et, si possible, une reproduction. Seule la branche `main` est maintenue.
