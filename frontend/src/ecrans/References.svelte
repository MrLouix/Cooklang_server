<script>
  import { onMount } from 'svelte';
  import Markdown from '../composants/Markdown.svelte';
  import { api } from '../lib/api.js';
  import { app, tenter } from '../lib/etat.svelte.js';
  import { dateCourte } from '../lib/texte.js';

  let onglet = $state('fiches');
  let donnees = $state(null);
  let fiche = $state(null); // { nom, contenu, nouvelle }
  let nomFiche = $state('');
  let url = $state('');
  let titreLien = $state('');
  let mode = $state('a_la_demande');
  let question = $state('');
  let resultats = $state(null);
  let occupe = $state(false);
  let fichier = $state();
  let minuteur;

  const ETATS = {
    en_attente: ['Indexation en cours', 'alerte'],
    indexe: ['Indexé', 'ok'],
    accessible: ['Accessible', 'ok'],
    inaccessible: ['Inaccessible', 'danger'],
    erreur: ['Erreur', 'danger'],
  };
  const MODES = { copie_locale: 'Copie locale', a_la_demande: 'À la demande' };

  async function charger() {
    donnees = (await tenter(() => api.get('/api/references'))) ?? donnees;
    clearTimeout(minuteur);
    if (donnees?.sources.some((s) => s.etat === 'en_attente')) minuteur = setTimeout(charger, 2000);
  }

  async function ouvrirFiche(nom) {
    const f = await tenter(() => api.get(`/api/references/fiches/${encodeURIComponent(nom)}`));
    if (f) fiche = { ...f, nouvelle: false };
  }

  function nouvelleFiche() {
    const nom = nomFiche.trim();
    if (!nom) return;
    fiche = { nom, contenu: donnees.gabarit.replace('{titre}', nom.charAt(0).toUpperCase() + nom.slice(1)), nouvelle: true };
    nomFiche = '';
  }

  async function enregistrerFiche() {
    const r = await tenter(
      () => api.put(`/api/references/fiches/${encodeURIComponent(fiche.nom)}`, { contenu: fiche.contenu }),
      'Fiche enregistrée.',
    );
    if (r) {
      fiche = null;
      charger();
    }
  }

  async function supprimerFiche() {
    if (!confirm(`Supprimer la fiche « ${fiche.nom} » ?`)) return;
    if ((await tenter(() => api.suppr(`/api/references/fiches/${encodeURIComponent(fiche.nom)}`))) !== undefined) {
      fiche = null;
      charger();
    }
  }

  async function ajouterDocuments(evenement) {
    occupe = true;
    for (const f of evenement.target.files)
      await tenter(() => api.envoyerFichier('/api/references', { fichier: f }), `« ${f.name} » ajouté.`);
    evenement.target.value = '';
    occupe = false;
    charger();
  }

  async function ajouterLien(evenement) {
    evenement.preventDefault();
    occupe = true;
    const r = await tenter(
      () => api.envoyerFichier('/api/references', { url: url.trim(), mode, titre: titreLien.trim() || null }),
      'Lien ajouté.',
    );
    occupe = false;
    if (r) {
      url = titreLien = '';
      charger();
    }
  }

  async function action(promesse) {
    await tenter(promesse);
    charger();
  }

  async function rechercher(evenement) {
    evenement?.preventDefault();
    resultats = question.trim() ? ((await tenter(() => api.get('/api/references/recherche', { q: question.trim() }))) ?? []) : null;
  }

  onMount(() => {
    charger();
    return () => clearTimeout(minuteur);
  });
</script>

<div class="ecran">
  <header class="entete">
    {#if fiche}
      <button class="btn discret icone" onclick={() => (fiche = null)} aria-label="Retour">←</button>
      <h1>Fiche : {fiche.nom}</h1>
    {:else}
      <h1>Base documentaire</h1>
    {/if}
  </header>
  <div class="corps">
    {#if fiche}
      <p class="secondaire">Rubriques fixes ; une source par valeur. Les fiches font foi sur les autres sources.</p>
      <textarea class="code" bind:value={fiche.contenu} aria-label="Contenu de la fiche" spellcheck="false"></textarea>
      <div class="rangee" style="margin-top:10px">
        <button class="btn principal" onclick={enregistrerFiche} disabled={!app.enLigne}>Enregistrer</button>
        {#if !fiche.nouvelle}<button class="btn danger" onclick={supprimerFiche} disabled={!app.enLigne}>Supprimer</button>{/if}
      </div>
      <details class="carte" style="margin-top:14px">
        <summary>Aperçu</summary>
        <Markdown source={fiche.contenu} />
      </details>
    {:else if !donnees}
      <div class="vide">Chargement…</div>
    {:else}
      <div class="onglets" role="tablist">
        <button class:actif={onglet === 'fiches'} onclick={() => (onglet = 'fiches')}>Fiches ({donnees.fiches.length})</button>
        <button class:actif={onglet === 'sources'} onclick={() => (onglet = 'sources')}>Sources ({donnees.sources.length})</button>
        <button class:actif={onglet === 'recherche'} onclick={() => (onglet = 'recherche')}>Recherche</button>
      </div>

      {#if onglet === 'fiches'}
        {#if donnees.fiches.length === 0}
          <div class="vide">
            Aucune fiche. Crée la première (brioche, pâte à choux, crèmes cuites…) ou demande à l'assistant d'en proposer une.
          </div>
        {/if}
        <ul class="liste">
          {#each donnees.fiches as f (f.nom)}
            <li>
              <button class="element" onclick={() => ouvrirFiche(f.nom)}
                ><div class="titre">{f.nom}</div>
                <div class="secondaire">{f.chemin}</div></button
              >
            </li>
          {/each}
        </ul>
        <form class="rangee" onsubmit={(e) => (e.preventDefault(), nouvelleFiche())} style="flex-wrap:nowrap">
          <input type="text" placeholder="Nom de la famille (ex. brioche)" bind:value={nomFiche} aria-label="Nom de la nouvelle fiche" />
          <button class="btn" type="submit">Créer</button>
        </form>
      {:else if onglet === 'sources'}
        <section class="carte">
          <h2>Ajouter un document</h2>
          <p class="secondaire">
            PDF, EPUB, Markdown ou texte. Converti et indexé sur le serveur ; l'original est conservé et ne quitte pas la machine.
          </p>
          <input type="file" bind:this={fichier} onchange={ajouterDocuments} accept=".pdf,.epub,.md,.markdown,.txt" multiple hidden />
          <button class="btn" onclick={() => fichier.click()} disabled={occupe || !app.enLigne}>Choisir des fichiers</button>
        </section>
        <form class="carte" onsubmit={ajouterLien}>
          <h2>Ajouter un lien</h2>
          <input type="url" placeholder="https://…" bind:value={url} required aria-label="Adresse de la page" style="margin-bottom:8px" />
          <input type="text" placeholder="Titre (facultatif)" bind:value={titreLien} aria-label="Titre du lien" style="margin-bottom:8px" />
          <select bind:value={mode} aria-label="Mode de consultation" style="margin-bottom:8px">
            <option value="a_la_demande">À la demande — site interrogé en priorité lors d'une recherche web</option>
            <option value="copie_locale">Copie locale — page téléchargée et indexée</option>
          </select>
          <button class="btn" type="submit" disabled={occupe || !app.enLigne}>Vérifier et ajouter</button>
          <p class="secondaire" style="margin-bottom:0">Seules les pages publiques, sans compte ni paiement, sont acceptées.</p>
        </form>
        {#each donnees.sources as s (s.id)}
          <div class="carte" class:inactif={!s.actif}>
            <div class="rangee">
              <strong style="flex:1;min-width:0;word-break:break-word">{s.titre}</strong>
              <span class="etiquette {ETATS[s.etat]?.[1]}">{ETATS[s.etat]?.[0] ?? s.etat}</span>
            </div>
            <div class="secondaire">
              {s.type === 'lien' ? MODES[s.mode] : 'Document'} · ajouté le {dateCourte(s.ajoutee_le)}{s.passages
                ? ` · ${s.passages} passage(s) indexé(s)`
                : ''}
            </div>
            {#if s.url}<a class="secondaire" href={s.url} target="_blank" rel="noopener noreferrer" style="word-break:break-all">{s.url}</a
              >{/if}
            {#if s.erreur}<div class="encart {s.etat === 'indexe' ? 'alerte' : 'danger'}">{s.erreur}</div>{/if}
            <div class="rangee" style="margin-top:8px">
              <label class="ligne" style="min-height:36px">
                <input
                  type="checkbox"
                  checked={s.actif}
                  onchange={(e) => action(() => api.patch(`/api/references/${s.id}`, { actif: e.target.checked }))}
                />
                Active
              </label>
              <span class="pousser"></span>
              {#if s.type === 'lien'}<button class="btn petit" onclick={() => action(() => api.post(`/api/references/${s.id}/rafraichir`))}
                  >Revérifier</button
                >{/if}
              <button
                class="btn petit danger"
                onclick={() => confirm(`Retirer « ${s.titre} » ?`) && action(() => api.suppr(`/api/references/${s.id}`))}>Retirer</button
              >
            </div>
          </div>
        {/each}
      {:else}
        <form class="rangee" onsubmit={rechercher} style="flex-wrap:nowrap;margin-bottom:12px">
          <input
            type="search"
            placeholder="hydratation brioche, température à cœur…"
            bind:value={question}
            aria-label="Rechercher dans la base"
          />
          <button class="btn" type="submit">Chercher</button>
        </form>
        {#if resultats?.length === 0}<div class="vide">Aucun passage trouvé.</div>{/if}
        {#each resultats ?? [] as r}
          <div class="carte">
            <div class="rangee">
              <strong style="flex:1">{r.titre}</strong>
              {#if r.type === 'fiche'}<span class="etiquette accent">Fiche</span>{/if}
              {#if r.page}<span class="etiquette">p. {r.page}</span>{/if}
            </div>
            <Markdown source={r.extrait} />
          </div>
        {/each}
      {/if}
    {/if}
  </div>
</div>

<style>
  .inactif {
    opacity: 0.6;
  }
  summary {
    cursor: pointer;
    font-weight: 600;
  }
</style>
