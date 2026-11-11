<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { app, appliquerTheme, tenter } from '../lib/etat.svelte.js';
  import { dateComplete, euros } from '../lib/texte.js';

  let { quota, protege } = $props();
  let onglet = $state('etat');
  let synchro = $state(null);
  let sante = $state(null);
  let memoire = $state([]);
  let ouvert = $state(null);
  let occupe = $state(false);

  const CIBLES = {
    github: 'GitHub (recettes)',
    'github-agent': 'GitHub (agent)',
    drive: 'Google Drive',
    import: 'Import depuis Drive',
    conflit: 'Conflit',
  };
  const part = $derived(quota ? Math.min(100, (quota.cout / quota.credit) * 100) : 0);

  async function charger() {
    [synchro, sante, memoire] = await Promise.all([
      tenter(() => api.get('/api/synchro')),
      tenter(() => api.get('/api/sante')),
      tenter(() => api.get('/api/memoire')).then((m) => m ?? []),
    ]);
  }

  async function resynchroniser() {
    occupe = true;
    const r = await tenter(() => api.post('/api/synchro'));
    occupe = false;
    if (r) synchro = r;
  }

  async function enregistrerMemoire(m) {
    await tenter(
      () => api.put(`/api/memoire/${m.fichier}`, { contenu: m.contenu }),
      'Mémoire enregistrée — appliquée dès le prochain message.',
    );
  }

  async function deconnecter() {
    await api.post('/api/deconnexion');
    location.reload();
  }

  onMount(charger);
</script>

<div class="ecran">
  <header class="entete"><h1>Système</h1></header>
  <div class="corps">
    <div class="onglets" role="tablist">
      <button class:actif={onglet === 'etat'} onclick={() => (onglet = 'etat')}>État</button>
      <button class:actif={onglet === 'memoire'} onclick={() => (onglet = 'memoire')}>Mémoire</button>
      <button class:actif={onglet === 'synchro'} onclick={() => (onglet = 'synchro')}>Synchro</button>
    </div>

    {#if onglet === 'etat'}
      <section class="carte">
        <h2>Crédit du mois</h2>
        {#if quota}
          <div
            class="jauge"
            role="progressbar"
            aria-valuenow={Math.round(part)}
            aria-valuemin="0"
            aria-valuemax="100"
            aria-label="Part du crédit mensuel consommée"
          >
            <div style="width:{part}%" class:plein={part >= 90}></div>
          </div>
          <div class="rangee">
            <strong>{euros(quota.cout)}</strong><span class="secondaire"
              >sur {euros(quota.credit)} · {quota.tours} tour(s) en {quota.mois}</span
            >
          </div>
          <p class="secondaire">
            Coût estimé renvoyé par le CLI, cumulé par mois. Le plafond affiché est une valeur de configuration, à ajuster au crédit réel du
            compte.
          </p>
          {#if quota.atteint}<div class="encart danger">Le CLI a signalé un crédit épuisé ce mois-ci.</div>{/if}
          {#if quota.historique.length > 1}
            <ul class="liste secondaire">
              {#each quota.historique.slice(1) as h}<li>{h.mois} : {euros(h.cout)} · {h.tours} tour(s)</li>{/each}
            </ul>
          {/if}
        {:else}
          <div class="secondaire">Indisponible hors connexion.</div>
        {/if}
      </section>

      <section class="carte">
        <h2>Composants</h2>
        {#if sante}
          <dl>
            <dt>Moteur</dt>
            <dd>{sante.moteur}{sante.moteur === 'factice' ? ' (démonstration, aucune réponse réelle)' : ''}</dd>
            <dt>CLI Claude</dt>
            <dd>{sante.cli}</dd>
            <dt>Modèle par défaut</dt>
            <dd>{sante.modele_defaut}</dd>
            <dt>Git</dt>
            <dd>{sante.git}</dd>
            <dt>rclone</dt>
            <dd>{sante.rclone}</dd>
            <dt>Node (parseur Cooklang)</dt>
            <dd>{sante.node}</dd>
            <dt>OCR</dt>
            <dd>{sante.ocr ? 'disponible' : 'absent'}</dd>
            <dt>Tours en file</dt>
            <dd>{sante.file}</dd>
          </dl>
        {/if}
      </section>

      <section class="carte">
        <h2>Apparence</h2>
        <div class="onglets" style="margin:0">
          {#each [['auto', 'Automatique'], ['light', 'Clair'], ['dark', 'Sombre']] as [valeur, nom]}
            <button class:actif={app.theme === valeur} onclick={() => appliquerTheme(valeur)}>{nom}</button>
          {/each}
        </div>
      </section>
      {#if protege}<button class="btn" onclick={deconnecter}>Se déconnecter</button>{/if}
    {:else if onglet === 'memoire'}
      <p class="secondaire">
        Faits appris au fil des discussions, relus par l'assistant à chaque message. L'assistant propose ses ajouts ; tu peux aussi les
        modifier ici.
      </p>
      {#each memoire as m (m.fichier)}
        <details class="carte" open={ouvert === m.fichier} ontoggle={(e) => e.target.open && (ouvert = m.fichier)}>
          <summary><strong>{m.fichier}</strong></summary>
          <textarea
            class="code"
            bind:value={m.contenu}
            style="margin-top:10px;min-height:200px"
            aria-label={'Contenu de ' + m.fichier}
            spellcheck="false"></textarea>
          <button class="btn principal" style="margin-top:8px" onclick={() => enregistrerMemoire(m)} disabled={!app.enLigne}
            >Enregistrer</button
          >
        </details>
      {/each}
    {:else if synchro}
      <section class="carte">
        <h2>Destinations</h2>
        <dl>
          <dt>GitHub</dt>
          <dd>{synchro.etat.github ? 'configuré' : 'non configuré'}</dd>
          <dt>Google Drive</dt>
          <dd>{synchro.etat.drive ? synchro.etat.destination : 'non configuré'}</dd>
          <dt>Dernier commit</dt>
          <dd>{synchro.etat.dernier_commit?.slice(0, 8) ?? '—'}</dd>
          {#if synchro.etat.drive}
            <dt>Miroir Drive</dt>
            <dd>
              {#if synchro.etat.dernier_commit === synchro.etat.dernier_commit_synchronise}<span class="etiquette ok">à jour</span>
              {:else}<span class="etiquette alerte">en retard</span>{/if}
            </dd>
          {/if}
        </dl>
        {#if synchro.etat.conflits.length}
          <div class="encart alerte">
            <strong>Conflits à départager</strong> — deux versions conservées :
            <ul>
              {#each synchro.etat.conflits as c}<li>{c}</li>{/each}
            </ul>
          </div>
        {/if}
        {#if synchro.bilan?.importes?.length}<div class="encart ok">Importé depuis Drive : {synchro.bilan.importes.join(', ')}</div>{/if}
        <button class="btn principal" onclick={resynchroniser} disabled={occupe || !app.enLigne}
          >{occupe ? 'Synchronisation…' : 'Resynchroniser'}</button
        >
      </section>
      <h2 style="margin:16px 0 8px">Journal</h2>
      {#if synchro.journal.length === 0}<div class="vide">Aucune synchronisation pour l'instant.</div>{/if}
      <ul class="liste">
        {#each synchro.journal as j (j.id)}
          <li class="carte" style="padding:10px 12px;margin-bottom:6px">
            <div class="rangee">
              <strong style="flex:1">{CIBLES[j.cible] ?? j.cible}</strong>
              <span class="etiquette {j.resultat === 'ok' ? 'ok' : j.resultat === 'conflit' ? 'alerte' : 'danger'}"
                >{j.resultat === 'echec' ? 'échec' : j.resultat}</span
              >
            </div>
            <div class="secondaire">{dateComplete(j.date)}{j.fichiers.length ? ' · ' + j.fichiers.join(', ') : ''}</div>
            {#if j.erreur}<div class="secondaire" style="color:var(--danger)">{j.erreur}</div>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</div>

<style>
  .jauge {
    height: 10px;
    background: var(--surface-2);
    border-radius: 999px;
    overflow: hidden;
    margin-bottom: 8px;
  }
  .jauge div {
    height: 100%;
    background: var(--accent);
    border-radius: 999px;
  }
  .jauge div.plein {
    background: var(--danger);
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 6px 14px;
    margin: 0;
    font-size: 0.92rem;
  }
  dt {
    color: var(--texte-2);
  }
  dd {
    margin: 0;
    word-break: break-word;
  }
  summary {
    cursor: pointer;
    min-height: 32px;
    display: flex;
    align-items: center;
  }
</style>
