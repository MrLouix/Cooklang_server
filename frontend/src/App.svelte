<script>
  import { onMount } from 'svelte';
  import { api } from './lib/api.js';
  import { app, appliquerTheme } from './lib/etat.svelte.js';
  import Chat from './ecrans/Chat.svelte';
  import Discussions from './ecrans/Discussions.svelte';
  import Parametres from './ecrans/Parametres.svelte';
  import Recette from './ecrans/Recette.svelte';
  import Recettes from './ecrans/Recettes.svelte';
  import References from './ecrans/References.svelte';
  import Systeme from './ecrans/Systeme.svelte';

  const ONGLETS = [
    { ecran: 'discussions', nom: 'Discussions', icone: '💬' },
    { ecran: 'recettes', nom: 'Recettes', icone: '📖' },
    { ecran: 'references', nom: 'Références', icone: '📚' },
    { ecran: 'parametres', nom: 'Paramètres', icone: '⚙️' },
    { ecran: 'systeme', nom: 'Système', icone: '🩺' },
  ];

  let session = $state(null);
  let motDePasse = $state('');
  let erreur = $state('');
  let quota = $state(null);

  async function verifier() {
    try {
      session = await api.get('/api/session');
    } catch {
      session = { protege: false, connecte: true }; // hors connexion : on affiche ce qui est en cache
    }
    if (session.connecte) quota = await api.get('/api/quota').catch(() => null);
  }

  async function connecter(e) {
    e.preventDefault();
    erreur = '';
    try {
      await api.post('/api/connexion', { mot_de_passe: motDePasse });
      motDePasse = '';
      await verifier();
    } catch (err) {
      erreur = err.message;
    }
  }

  onMount(() => {
    appliquerTheme();
    verifier();
    const deconnecte = () => (session = { protege: true, connecte: false });
    window.addEventListener('ac:deconnecte', deconnecte);
    window.addEventListener('ac:quota', verifier);
    return () => window.removeEventListener('ac:deconnecte', deconnecte);
  });

  const dansChat = $derived(app.route.ecran === 'discussions' && app.route.param);
</script>

{#if session === null}
  <div class="vide">Chargement…</div>
{:else if !session.connecte}
  <form
    class="corps"
    onsubmit={connecter}
    style="display:flex;flex-direction:column;justify-content:center;gap:12px;max-width:360px;margin:auto;width:100%"
  >
    <h1>Aide Culinaire</h1>
    <input type="password" class="champ" placeholder="Mot de passe" bind:value={motDePasse} autocomplete="current-password" />
    {#if erreur}<div class="encart danger">{erreur}</div>{/if}
    <button class="btn principal" type="submit">Se connecter</button>
  </form>
{:else}
  {#if !app.enLigne}
    <div class="bandeau alerte">Hors connexion — consultation seule, l'envoi est désactivé.</div>
  {:else if quota?.secours_actif}
    <div class="bandeau alerte">Crédit du moteur principal épuisé : les réponses passent par l'API, facturée à l'usage.</div>
  {:else if quota?.atteint}
    <div class="bandeau danger">Crédit mensuel épuisé : l'assistant est indisponible jusqu'au renouvellement.</div>
  {/if}

  {#if app.route.ecran === 'discussions' && app.route.param}
    {#key app.route.param}<Chat id={app.route.param} />{/key}
  {:else if app.route.ecran === 'discussions'}
    <Discussions />
  {:else if app.route.ecran === 'recettes' && app.route.param}
    {#key app.route.param}<Recette chemin={app.route.param} />{/key}
  {:else if app.route.ecran === 'recettes'}
    <Recettes />
  {:else if app.route.ecran === 'references'}
    <References />
  {:else if app.route.ecran === 'parametres'}
    <Parametres />
  {:else if app.route.ecran === 'systeme'}
    <Systeme {quota} protege={session.protege} />
  {:else}
    <Discussions />
  {/if}

  {#if !dansChat}
    <nav class="bas" aria-label="Navigation principale">
      {#each ONGLETS as onglet (onglet.ecran)}
        <a
          href={'#/' + onglet.ecran}
          class:actif={app.route.ecran === onglet.ecran}
          aria-current={app.route.ecran === onglet.ecran ? 'page' : undefined}
        >
          <span aria-hidden="true">{onglet.icone}</span>{onglet.nom}
        </a>
      {/each}
    </nav>
  {/if}
{/if}

<div class="notifications" aria-live="polite">
  {#each app.messages as message (message.id)}
    <div class="notification {message.genre}">{message.texte}</div>
  {/each}
</div>
