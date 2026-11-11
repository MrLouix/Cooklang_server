<script>
  import { api } from '../lib/api.js';
  import { aller, app, tenter } from '../lib/etat.svelte.js';
  import { dateCourte } from '../lib/texte.js';

  let discussions = $state(null);
  let recherche = $state('');
  let archivees = $state(false);
  let minuteur;

  async function charger() {
    const params = { archivees };
    if (recherche.trim()) params.q = recherche.trim();
    discussions = (await tenter(() => api.get('/api/discussions', params))) ?? discussions ?? [];
  }

  $effect(() => {
    archivees;
    recherche;
    clearTimeout(minuteur);
    minuteur = setTimeout(charger, recherche ? 250 : 0);
  });

  async function nouvelle() {
    const d = await tenter(() => api.post('/api/discussions', {}));
    if (d) aller('discussions', d.id);
  }
</script>

<div class="ecran">
  <header class="entete">
    <h1>Discussions</h1>
    <button class="btn petit" class:principal={archivees} onclick={() => (archivees = !archivees)} aria-pressed={archivees}
      >Archivées</button
    >
  </header>
  <div class="corps">
    <input
      type="search"
      placeholder="Rechercher dans les titres et les messages"
      bind:value={recherche}
      aria-label="Rechercher une discussion"
      style="margin-bottom:12px"
    />
    {#if discussions === null}
      <div class="vide">Chargement…</div>
    {:else if discussions.length === 0}
      <div class="vide">
        {recherche
          ? 'Aucune discussion ne correspond.'
          : archivees
            ? 'Aucune discussion archivée.'
            : 'Aucune discussion. Soumets une recette pour commencer.'}
      </div>
    {:else}
      <ul class="liste">
        {#each discussions as d (d.id)}
          <li>
            <a class="element" href={'#/discussions/' + d.id}>
              <div class="rangee" style="flex-wrap:nowrap">
                <div class="titre" style="flex:1">{d.titre}</div>
                <span class="secondaire">{dateCourte(d.modifie_le)}</span>
              </div>
              {#if d.extrait}<div class="secondaire extrait">{d.extrait.replaceAll('**', '')}</div>{/if}
              <div class="rangee" style="margin-top:6px">
                <span class="etiquette">{d.modele}</span>
                {#if d.domaine}<span class="etiquette">{d.domaine}</span>{/if}
                {#if d.en_cours}<span class="etiquette accent">Réponse en cours</span>{/if}
                {#each d.recettes as r}<span class="etiquette ok">{r.split('/').pop().replace('.cook', '')}</span>{/each}
              </div>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
  <button class="btn principal nouveau" onclick={nouvelle} disabled={!app.enLigne}>＋ Nouvelle discussion</button>
</div>

<style>
  .nouveau {
    margin: 0 14px 12px;
    flex: none;
  }
  .extrait {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin-top: 2px;
  }
</style>
