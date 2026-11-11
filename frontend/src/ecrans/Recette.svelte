<script>
  import { onMount } from 'svelte';
  import Diff from '../composants/Diff.svelte';
  import { api, cheminRecette } from '../lib/api.js';
  import { aller, app, tenter } from '../lib/etat.svelte.js';
  import { colorerCook, dateComplete } from '../lib/texte.js';

  let { chemin } = $props();
  let recette = $state(null);
  let onglet = $state('recette');
  let version = $state(null); // { sha, contenu }
  const base = $derived('/api/recettes/' + cheminRecette(chemin));
  const nom = $derived(
    chemin
      .split('/')
      .pop()
      .replace(/\.cook$/, ''),
  );

  async function charger() {
    recette = await tenter(() => api.get(base));
  }

  async function voir(sha) {
    version = version?.sha === sha ? null : await tenter(() => api.get(`${base}/version/${sha}`));
  }

  async function restaurer(sha) {
    if (!confirm("Restaurer cette version ? Un nouveau commit sera créé, rien n'est effacé.")) return;
    if (await tenter(() => api.post(`${base}/restaurer`, { sha }), 'Version restaurée.')) {
      version = null;
      await charger();
      onglet = 'recette';
    }
  }

  async function discuter() {
    const d = await tenter(() => api.post('/api/discussions', { recette: chemin }));
    if (d) aller('discussions', d.id);
  }

  onMount(charger);
</script>

<div class="ecran">
  <header class="entete">
    <a class="btn discret icone" href="#/recettes" aria-label="Retour aux recettes">←</a>
    <h1>{nom}</h1>
  </header>
  <div class="corps">
    {#if !recette}
      <div class="vide">Chargement…</div>
    {:else}
      <div class="secondaire" style="margin-bottom:10px">{chemin}</div>
      <div class="onglets" role="tablist">
        <button class:actif={onglet === 'recette'} onclick={() => (onglet = 'recette')}>Recette</button>
        <button class:actif={onglet === 'historique'} onclick={() => (onglet = 'historique')}
          >Historique ({recette.historique.length})</button
        >
        <button class:actif={onglet === 'discussions'} onclick={() => (onglet = 'discussions')}
          >Discussions ({recette.discussions.length})</button
        >
      </div>

      {#if onglet === 'recette'}
        <!-- colorerCook échappe tout le texte avant d'ajouter ses balises -->
        <pre class="cook">{@html colorerCook(recette.contenu)}</pre>
      {:else if onglet === 'historique'}
        <ul class="liste">
          {#each recette.historique as h, i (h.sha)}
            <li class="carte">
              <div class="rangee">
                <strong style="flex:1;min-width:0">{h.sujet}</strong>
                {#if i === 0}<span class="etiquette ok">Version actuelle</span>{/if}
              </div>
              <div class="secondaire">{dateComplete(h.date)} · {h.sha.slice(0, 8)}</div>
              {#if h.corps}<div class="secondaire" style="white-space:pre-wrap">{h.corps}</div>{/if}
              {#if i > 0}
                <div class="rangee" style="margin-top:8px">
                  <button class="btn petit" onclick={() => voir(h.sha)}
                    >{version?.sha === h.sha ? 'Masquer' : 'Comparer à la version actuelle'}</button
                  >
                  <button class="btn petit" onclick={() => restaurer(h.sha)} disabled={!app.enLigne}>Restaurer</button>
                </div>
                {#if version?.sha === h.sha}
                  <div style="margin-top:10px"><Diff avant={recette.contenu} apres={version.contenu} /></div>
                {/if}
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        {#if recette.discussions.length === 0}
          <div class="vide">Aucune discussion n'a créé ou modifié cette recette.</div>
        {/if}
        <ul class="liste">
          {#each recette.discussions as d (d.id + d.commit_sha)}
            <li>
              <a class="element" href={'#/discussions/' + d.id}>
                <div class="titre">{d.titre}</div>
                <div class="secondaire">{d.type} · {dateComplete(d.traite_le)}</div>
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    {/if}
  </div>
  <button class="btn principal" style="margin:0 14px 12px;flex:none" onclick={discuter} disabled={!app.enLigne || !recette}
    >💬 Discuter de cette recette</button
  >
</div>
