<script>
  import { api, cheminRecette } from '../lib/api.js';
  import { tenter } from '../lib/etat.svelte.js';

  let categories = $state(null);
  let recherche = $state('');
  let minuteur;

  async function charger() {
    const r = await tenter(() => api.get('/api/recettes', recherche.trim() ? { q: recherche.trim() } : undefined));
    categories = r?.categories ?? categories ?? [];
  }

  $effect(() => {
    recherche;
    clearTimeout(minuteur);
    minuteur = setTimeout(charger, recherche ? 250 : 0);
  });

  const total = $derived((categories ?? []).reduce((n, c) => n + c.recettes.length, 0));
</script>

<div class="ecran">
  <header class="entete">
    <h1>Recettes</h1>
    {#if categories}<span class="secondaire">{total} fichier{total > 1 ? 's' : ''}</span>{/if}
  </header>
  <div class="corps">
    <input type="search" placeholder="Rechercher un nom, un ingrédient, une étape" bind:value={recherche} aria-label="Rechercher une recette" style="margin-bottom:12px" />
    {#if categories === null}
      <div class="vide">Chargement…</div>
    {:else if categories.length === 0}
      <div class="vide">{recherche ? 'Aucune recette ne correspond.' : "Aucune recette pour l'instant. Elles apparaîtront ici après ton premier « Enregistrer »."}</div>
    {:else}
      {#each categories as categorie (categorie.nom)}
        <details class="carte" open={Boolean(recherche) || categories.length <= 4}>
          <summary><h2>{categorie.nom}</h2><span class="etiquette">{categorie.recettes.length}</span></summary>
          <ul class="liste" style="margin-top:10px">
            {#each categorie.recettes as r (r.chemin)}
              <li>
                <a class="element" href={'#/recettes/' + cheminRecette(r.chemin)}>
                  <div class="titre">{r.nom}</div>
                  {#if r.conflit}<span class="etiquette alerte">Copie de conflit à départager</span>{/if}
                  {#if r.extrait}<div class="secondaire">{r.extrait}</div>{/if}
                </a>
              </li>
            {/each}
          </ul>
        </details>
      {/each}
    {/if}
  </div>
</div>

<style>
  summary { display: flex; align-items: center; gap: 8px; cursor: pointer; list-style: none; min-height: 32px; }
  summary::-webkit-details-marker { display: none; }
  summary h2 { flex: 1; }
  details .element { background: var(--surface-2); border-color: transparent; }
</style>
