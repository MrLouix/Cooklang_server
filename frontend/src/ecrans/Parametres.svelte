<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { app, notifier, tenter } from '../lib/etat.svelte.js';

  // Le formulaire est construit à partir du schéma servi par l'API : un réglage ajouté côté serveur apparaît sans toucher à cet écran (PA-8).
  let schema = $state(null);
  let valeurs = $state(null);
  let defauts = $state(null);
  let etat = $state('');
  let nouvelleEtiquette = $state('');
  let nouveauDomaine = $state('');
  let minuteur;

  onMount(async () => {
    const [s, p] = await Promise.all([tenter(() => api.get('/api/parametres/schema')), tenter(() => api.get('/api/parametres'))]);
    schema = s;
    valeurs = p?.valeurs;
    defauts = p?.defauts;
  });

  function enregistrer(delai = 0) {
    etat = 'Modifications en attente…';
    clearTimeout(minuteur);
    minuteur = setTimeout(async () => {
      try {
        const r = await api.put('/api/parametres', $state.snapshot(valeurs));
        valeurs = r.valeurs;
        etat = 'Enregistré — appliqué dès le prochain message.';
      } catch (erreur) {
        etat = '';
        notifier(erreur.message, 'erreur');
      }
    }, delai);
  }

  function basculerNiveau(reglage, option, coche) {
    if (coche) valeurs[reglage.cle][option] = 'stricte';
    else delete valeurs[reglage.cle][option];
    enregistrer();
  }

  function basculerCase(cle, valeur, coche) {
    valeurs[cle] = coche ? [...valeurs[cle], valeur] : valeurs[cle].filter((v) => v !== valeur);
    enregistrer();
  }

  function ajouterEtiquette(cle) {
    const nom = nouvelleEtiquette.trim();
    if (!nom || valeurs[cle].some((e) => e.nom.toLowerCase() === nom.toLowerCase())) return;
    valeurs[cle].push({ nom, niveau: 'souple' });
    nouvelleEtiquette = '';
    enregistrer();
  }

  function ajouterDomaine(cle) {
    const nom = nouveauDomaine.trim();
    if (!nom || nom in valeurs[cle]) return;
    valeurs[cle][nom] = '';
    nouveauDomaine = '';
    enregistrer();
  }

  function supprimerDomaine(cle, nom) {
    if (valeurs[cle][nom] && !confirm(`Supprimer le domaine « ${nom} » et son texte ?`)) return;
    delete valeurs[cle][nom];
    enregistrer();
  }

  function reinitialiser() {
    if (!confirm('Revenir aux valeurs par défaut pour tous les réglages ? Les textes par domaine seront vidés.')) return;
    valeurs = structuredClone($state.snapshot(defauts));
    enregistrer();
  }
</script>

<div class="ecran">
  <header class="entete">
    <h1>Paramètres</h1>
    <button class="btn petit" onclick={reinitialiser} disabled={!valeurs || !app.enLigne}>Par défaut</button>
  </header>
  <div class="corps">
    {#if !schema || !valeurs}
      <div class="vide">Chargement…</div>
    {:else}
      <fieldset disabled={!app.enLigne}>
        {#each schema.sections as section (section.cle)}
          <section class="carte">
            <h2>{section.titre}</h2>
            {#each section.reglages as r (r.cle)}
              <div class="reglage">
                {#if r.controle === 'liste'}
                  <label for={r.cle}>{r.libelle}</label>
                  <select id={r.cle} bind:value={valeurs[r.cle]} onchange={() => enregistrer()}>
                    {#each r.valeurs as v}<option value={v.valeur}>{v.libelle}</option>{/each}
                  </select>
                {:else if r.controle === 'nombre'}
                  <label for={r.cle}>{r.libelle} <span class="secondaire">({r.min} à {r.max} {r.unite ?? ''})</span></label>
                  <input id={r.cle} type="number" min={r.min} max={r.max} bind:value={valeurs[r.cle]} onchange={() => enregistrer()} inputmode="numeric" />
                {:else if r.controle === 'case'}
                  <label class="ligne">
                    <input type="checkbox" bind:checked={valeurs[r.cle]} onchange={() => enregistrer()} />
                    {r.libelle}
                  </label>
                {:else if r.controle === 'cases'}
                  <div class="libelle">{r.libelle}</div>
                  {#each r.valeurs as v}
                    <label class="ligne">
                      <input type="checkbox" checked={valeurs[r.cle].includes(v.valeur)} onchange={(e) => basculerCase(r.cle, v.valeur, e.target.checked)} />
                      {v.libelle}
                    </label>
                  {/each}
                {:else if r.controle === 'cases_niveau'}
                  <div class="libelle">{r.libelle}</div>
                  {#each r.options as option}
                    <div class="double">
                      <label class="ligne">
                        <input type="checkbox" checked={option in valeurs[r.cle]} onchange={(e) => basculerNiveau(r, option, e.target.checked)} />
                        {option}
                      </label>
                      {#if option in valeurs[r.cle]}
                        <select bind:value={valeurs[r.cle][option]} onchange={() => enregistrer()} aria-label={'Niveau pour ' + option}>
                          {#each r.niveaux as n}<option value={n.valeur}>{n.libelle}</option>{/each}
                        </select>
                      {/if}
                    </div>
                  {/each}
                {:else if r.controle === 'etiquettes_niveau'}
                  <div class="libelle">{r.libelle}</div>
                  {#each valeurs[r.cle] as e, i (e.nom)}
                    <div class="double">
                      <span class="etiquette accent">{e.nom}</span>
                      <select bind:value={e.niveau} onchange={() => enregistrer()} aria-label={'Niveau pour ' + e.nom}>
                        {#each r.niveaux as n}<option value={n.valeur}>{n.libelle}</option>{/each}
                      </select>
                      <button class="btn petit discret" onclick={() => (valeurs[r.cle].splice(i, 1), enregistrer())} aria-label={'Retirer ' + e.nom}>✕</button>
                    </div>
                  {/each}
                  <form class="double" onsubmit={(e) => (e.preventDefault(), ajouterEtiquette(r.cle))}>
                    <input type="text" placeholder="Un ingrédient, puis Ajouter" bind:value={nouvelleEtiquette} aria-label="Ingrédient à éviter" />
                    <button class="btn petit" type="submit">Ajouter</button>
                  </form>
                {:else if r.controle === 'textes_domaines'}
                  <p class="secondaire">Un texte n'est transmis à l'assistant que si la discussion porte sur ce domaine. « Matériel » et « Forme des réponses » le sont toujours.</p>
                  {#each Object.keys(valeurs[r.cle]) as domaine (domaine)}
                    <div class="domaine">
                      <div class="rangee">
                        <label for={'d-' + domaine} style="flex:1">{domaine}</label>
                        <button class="btn petit discret" onclick={() => supprimerDomaine(r.cle, domaine)} aria-label={'Supprimer le domaine ' + domaine}>✕</button>
                      </div>
                      <textarea id={'d-' + domaine} rows="2" bind:value={valeurs[r.cle][domaine]} oninput={() => enregistrer(800)} placeholder="Préférences libres pour ce domaine"></textarea>
                    </div>
                  {/each}
                  <form class="double" onsubmit={(e) => (e.preventDefault(), ajouterDomaine(r.cle))}>
                    <input type="text" placeholder="Nouveau domaine" bind:value={nouveauDomaine} aria-label="Nom du nouveau domaine" />
                    <button class="btn petit" type="submit">Ajouter</button>
                  </form>
                {/if}
              </div>
            {/each}
          </section>
        {/each}
      </fieldset>
      <p class="secondaire">Les fichiers .cook restent toujours en grammes : les unités ne changent que la présentation dans la conversation.</p>
    {/if}
  </div>
  {#if etat}<div class="bandeau" style="background:var(--surface-2)" aria-live="polite">{etat}</div>{/if}
</div>

<style>
  fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
  .reglage { padding: 8px 0; border-top: 1px solid var(--bord); }
  .reglage:first-of-type { border-top: 0; }
  .reglage > label:not(.ligne), .libelle { display: block; font-weight: 550; margin-bottom: 6px; }
  .double { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
  .double > label, .double > input, .double > .etiquette { flex: 1; min-width: 0; }
  .double > select { flex: 1.2; min-width: 0; }
  .domaine { margin-bottom: 10px; }
</style>
