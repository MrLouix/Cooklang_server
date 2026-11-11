<script>
  import { api } from '../lib/api.js';
  import { app, notifier } from '../lib/etat.svelte.js';
  import { colorerCook } from '../lib/texte.js';
  import Diff from './Diff.svelte';
  import Markdown from './Markdown.svelte';

  /** proposition : objet de l'API ; surCorrection(texte, envoyer) : pré-remplit ou envoie un message. */
  let { proposition, surCorrection } = $props();

  // La carte vit sa vie après l'affichage : seule la valeur initiale de la proposition compte.
  // svelte-ignore state_referenced_locally
  let p = $state(proposition);
  // svelte-ignore state_referenced_locally
  let vue = $state(proposition.existe ? 'diff' : 'apercu');
  let occupe = $state(false);
  let blocage = $state(null); // { code, message, erreurs?, alertes? }
  let resultat = $state(null);

  const LIBELLES = { creation: 'Création', modification: 'Modification', variante: 'Variante' };
  const CIBLES = { recette: 'Recette', memoire: 'Mémoire', fiche: 'Fiche de référence' };
  const estCook = $derived(p.cible === 'recette');

  async function valider(params = {}) {
    occupe = true;
    try {
      const r = await api.post(`/api/propositions/${p.id}/valider`, undefined, params);
      p = r.proposition;
      resultat = r;
      blocage = null;
      notifier('Enregistré.');
    } catch (erreur) {
      const corps = erreur.corps || {};
      if (corps.code === 'syntaxe') {
        blocage = corps;
        surCorrection?.(corps.message_assistant, true); // F-7 : l'erreur est renvoyée à l'assistant
      } else if (corps.code === 'exclusions' || corps.code === 'gabarit') {
        blocage = corps;
      } else if (corps.code === 'fichier_modifie') {
        blocage = corps;
        p = { ...p, original: corps.original, existe: corps.original != null };
        vue = 'diff';
      } else {
        notifier(erreur.message, 'erreur');
        if (erreur.statut === 409) p = await api.get(`/api/propositions/${p.id}`);
      }
    } finally {
      occupe = false;
    }
  }

  async function ignorer() {
    occupe = true;
    try {
      p = await api.post(`/api/propositions/${p.id}/rejeter`);
    } catch (erreur) {
      notifier(erreur.message, 'erreur');
    } finally {
      occupe = false;
    }
  }
</script>

<section class="proposition" aria-label="Proposition de fichier">
  <header>
    <div class="rangee">
      <span class="etiquette accent">{CIBLES[p.cible]} · {LIBELLES[p.type]}</span>
      {#if p.etat === 'validee'}<span class="etiquette ok">Enregistrée</span>{/if}
      {#if p.etat === 'rejetee'}<span class="etiquette">Ignorée</span>{/if}
    </div>
    <div class="chemin">{p.chemin}</div>
  </header>

  {#if p.etat === 'en_attente'}
    {#if p.existe && p.type !== 'modification'}
      <div class="encart alerte">Un fichier porte déjà ce nom : l'enregistrer le remplacera.</div>
    {/if}
    {#if p.existe}
      <div class="onglets" role="tablist">
        <button class:actif={vue === 'diff'} onclick={() => (vue = 'diff')} role="tab" aria-selected={vue === 'diff'}>Différences</button>
        <button class:actif={vue === 'apercu'} onclick={() => (vue = 'apercu')} role="tab" aria-selected={vue === 'apercu'}>Aperçu</button>
      </div>
    {/if}
  {/if}

  {#if p.etat === 'en_attente' && vue === 'diff' && p.existe}
    <Diff avant={p.original} apres={p.contenu} />
  {:else if p.etat !== 'rejetee'}
    <details open={p.etat === 'en_attente'}>
      <summary class="secondaire">Contenu du fichier</summary>
      {#if estCook}
        <!-- colorerCook échappe tout le texte avant d'ajouter ses balises -->
        <pre class="cook">{@html colorerCook(p.contenu)}</pre>
      {:else}
        <div class="apercu-md"><Markdown source={p.contenu} /></div>
      {/if}
    </details>
  {/if}

  {#if blocage?.code === 'syntaxe' || blocage?.code === 'gabarit'}
    <div class="encart danger" role="alert">
      <strong>{blocage.message}</strong>
      <ul>{#each blocage.erreurs as e}<li>{e}</li>{/each}</ul>
      {#if blocage.code === 'syntaxe'}L'erreur a été renvoyée à l'assistant.{/if}
    </div>
  {:else if blocage?.code === 'exclusions'}
    <div class="encart danger" role="alert">
      <strong>Exclusion stricte</strong>
      <ul>{#each blocage.alertes as a}<li>{a.ingredient} — {a.exclusion}</li>{/each}</ul>
      <button class="btn petit danger" style="margin-top:8px" disabled={occupe} onclick={() => valider({ confirmer_exclusions: true })}>
        Enregistrer quand même
      </button>
    </div>
  {:else if blocage?.code === 'fichier_modifie'}
    <div class="encart alerte" role="alert">
      <strong>{blocage.message}</strong>
      <button class="btn petit" style="margin-top:8px" disabled={occupe} onclick={() => valider({ forcer: true, confirmer_exclusions: true })}>
        Remplacer la version actuelle
      </button>
    </div>
  {/if}

  {#if resultat}
    <div class="encart ok">
      Commit {resultat.commit?.slice(0, 8)} — synchronisation lancée.
      {#if resultat.conflits?.length}
        <br />Conflit avec Drive : la version du Drive est conservée dans {resultat.conflits.join(', ')}.
      {/if}
      {#each resultat.avertissements || [] as a}<br />{a}{/each}
    </div>
  {/if}

  {#if p.etat === 'en_attente'}
    <div class="actions">
      <button class="btn principal" disabled={occupe || !app.enLigne} onclick={() => valider()}>Enregistrer</button>
      <button class="btn" disabled={occupe} onclick={() => surCorrection?.(`Pour ${p.chemin} : `, false)}>Demander une correction</button>
      <button class="btn discret" disabled={occupe} onclick={ignorer}>Ignorer</button>
    </div>
  {/if}
</section>

<style>
  .proposition { border: 1.5px solid var(--accent); border-radius: var(--rayon); padding: 12px; margin: 10px 0; background: var(--surface); }
  header { margin-bottom: 10px; }
  .chemin { font-weight: 650; margin-top: 6px; word-break: break-word; }
  details summary { cursor: pointer; padding: 6px 0; }
  .apercu-md { padding: 10px; background: var(--surface-2); border-radius: 10px; }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .actions .principal { flex: 1 1 100%; }
  .actions .btn:not(.principal) { flex: 1; }
</style>
