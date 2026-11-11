<script>
  import { onMount, tick } from 'svelte';
  import Markdown from '../composants/Markdown.svelte';
  import Proposition from '../composants/Proposition.svelte';
  import { api, flux } from '../lib/api.js';
  import { aller, app, notifier, tenter } from '../lib/etat.svelte.js';
  import { dateCourte, euros, segments } from '../lib/texte.js';

  let { id } = $props();

  let discussion = $state(null);
  let messages = $state([]);
  let direct = $state(null); // réponse en cours : { texte, outils, position }
  let saisie = $state('');
  let pieces = $state([]);
  let menu = $state(false);
  let sante = $state(null);
  let zone;
  let champ;
  let fichier;
  let annulation = null;
  let colle = true; // l'affichage suit le bas tant que l'utilisateur n'a pas remonté

  const occupe = $derived(direct !== null);
  const coutTotal = $derived(messages.reduce((somme, m) => somme + (m.cout || 0), 0));

  async function defiler(force = false) {
    await tick();
    if (zone && (colle || force)) zone.scrollTop = zone.scrollHeight;
  }

  async function charger() {
    const d = await tenter(() => api.get(`/api/discussions/${id}`));
    if (!d) return;
    messages = d.messages.filter((m) => m.etat !== 'en_cours');
    discussion = d;
    await defiler(true);
    if (d.en_cours && app.enLigne) suivre('GET', `/api/discussions/${id}/flux`);
  }

  function surEvenement(genre, donnees) {
    if (genre === 'etat') direct = { texte: donnees.texte, outils: donnees.outils, position: donnees.position };
    else if (genre === 'debut') direct && (direct.position = 0);
    else if (genre === 'attente') direct && (direct.position = donnees.position);
    else if (genre === 'texte') direct && (direct.texte += donnees.delta);
    else if (genre === 'outil') direct?.outils.push(donnees);
    else if (genre === 'fin') {
      messages.push(donnees.message);
      discussion = { ...discussion, ...donnees.discussion, en_cours: false };
      direct = null;
      window.dispatchEvent(new Event('ac:quota'));
    } else if (genre === 'erreur') {
      messages.push(donnees.message_enregistre);
      direct = null;
      if (donnees.code === 'quota') window.dispatchEvent(new Event('ac:quota'));
    }
    defiler();
  }

  /** Suit un flux SSE ; si la connexion tombe (veille du téléphone), l'état est repris depuis la base (P-3). */
  async function suivre(methode, chemin, corps) {
    annulation?.abort();
    const controleur = (annulation = new AbortController());
    direct ??= { texte: '', outils: [], position: 0 };
    try {
      await flux(methode, chemin, corps, surEvenement, controleur.signal);
      if (direct && !controleur.signal.aborted) await charger(); // flux fermé sans conclusion
    } catch (erreur) {
      if (controleur.signal.aborted) return;
      direct = null;
      if (erreur.statut) notifier(erreur.message, 'erreur');
      else setTimeout(charger, 1500);
    }
  }

  async function envoyer(texte = saisie) {
    texte = texte.trim();
    if ((!texte && !pieces.length) || occupe || !app.enLigne) return;
    const jointes = pieces;
    messages.push({ id: 'local-' + Date.now(), role: 'user', contenu: texte, pieces: jointes, propositions: [], etat: 'termine' });
    saisie = '';
    pieces = [];
    colle = true;
    defiler(true);
    await suivre('POST', `/api/discussions/${id}/messages`, { texte, pieces: jointes });
  }

  function surCorrection(texte, envoyerDirect) {
    if (envoyerDirect && !occupe) envoyer(texte);
    else {
      saisie = texte;
      champ?.focus();
    }
  }

  async function joindre(evenement) {
    for (const f of evenement.target.files) {
      const piece = await tenter(() => api.envoyerFichier('/api/pieces', { fichier: f }));
      if (piece) pieces.push(piece);
    }
    evenement.target.value = '';
  }

  function coller(evenement) {
    const images = [...(evenement.clipboardData?.files || [])];
    if (images.length) {
      evenement.preventDefault();
      joindre({ target: { files: images, value: '' } });
    }
  }

  function touche(evenement) {
    if (evenement.key === 'Enter' && (evenement.ctrlKey || evenement.metaKey)) envoyer();
  }

  async function modifier(corps, message) {
    const d = await tenter(() => api.patch(`/api/discussions/${id}`, corps), message);
    if (d) discussion = { ...discussion, ...d };
  }

  function renommer() {
    const titre = prompt('Titre de la discussion', discussion.titre);
    if (titre?.trim()) modifier({ titre });
    menu = false;
  }

  async function archiver() {
    await modifier({ archivee: !discussion.archivee });
    aller('discussions');
  }

  async function supprimer() {
    if (!confirm('Supprimer définitivement cette discussion ?')) return;
    if ((await tenter(() => api.suppr(`/api/discussions/${id}`))) !== undefined) aller('discussions');
  }

  async function dupliquer(messageId) {
    const copie = await tenter(() => api.post(`/api/discussions/${id}/dupliquer`, { message_id: messageId ?? null }));
    if (copie) aller('discussions', copie.id);
  }

  onMount(() => {
    charger();
    api
      .get('/api/sante')
      .then((s) => (sante = s))
      .catch(() => {});
    const reveil = () => {
      if (document.visibilityState === 'visible' && (occupe || discussion?.en_cours)) {
        annulation?.abort();
        direct = null;
        charger();
      }
    };
    document.addEventListener('visibilitychange', reveil);
    return () => {
      document.removeEventListener('visibilitychange', reveil);
      annulation?.abort();
    };
  });
</script>

<div class="ecran">
  <header class="entete">
    <a class="btn discret icone" href="#/discussions" aria-label="Retour aux discussions">←</a>
    <h1>{discussion?.titre ?? '…'}</h1>
    <button class="btn discret icone" onclick={() => (menu = true)} aria-label="Options de la discussion">⋯</button>
  </header>

  <div class="corps fil" bind:this={zone} onscroll={() => (colle = zone.scrollHeight - zone.scrollTop - zone.clientHeight < 80)}>
    {#if discussion && messages.length === 0 && !direct}
      <div class="vide">
        {#if discussion.recette_contexte}
          Discussion à propos de <strong>{discussion.recette_contexte}</strong>.<br />Pose ta question.
        {:else}
          Colle une recette, décris un essai raté ou demande une nouvelle recette.
        {/if}
      </div>
    {/if}

    {#each messages as m (m.id)}
      {#if m.role === 'user'}
        <div class="message moi">
          {#if m.pieces?.length}
            <div class="pieces">
              {#each m.pieces as p}
                {#if p.type?.startsWith('image/')}
                  <img src={'/api/pieces/' + p.fichier} alt={p.nom} loading="lazy" />
                {:else}
                  <a class="etiquette" href={'/api/pieces/' + p.fichier} target="_blank" rel="noopener">📎 {p.nom}</a>
                {/if}
              {/each}
            </div>
          {/if}
          <div class="bulle">{m.contenu}</div>
        </div>
      {:else}
        <div class="message">
          {#if m.outils?.length}
            <div class="outils">
              {#each m.outils as o}<span class="etiquette" title={o.detail}>{o.nom}{o.detail ? ' · ' + o.detail.slice(0, 40) : ''}</span
                >{/each}
            </div>
          {/if}
          {#each segments(m.contenu) as s}
            {#if s.genre === 'texte'}
              <Markdown source={s.texte} />
            {:else}
              {@const p = m.propositions.find((x) => x.id === s.id)}
              {#if p}<Proposition proposition={p} {surCorrection} />{/if}
            {/if}
          {/each}
          {#if m.etat === 'erreur'}
            <div class="encart danger" role="alert">{m.erreur_message}</div>
          {/if}
          <div class="pied secondaire">
            <span>{dateCourte(m.cree_le)}{m.cout ? ' · ' + euros(m.cout) : ''}{m.moteur === 'api' ? ' · via API' : ''}</span>
            {#if typeof m.id === 'number'}
              <button class="lien" onclick={() => dupliquer(m.id)}>Dupliquer à partir d'ici</button>
            {/if}
          </div>
        </div>
      {/if}
    {/each}

    {#if direct}
      <div class="message" aria-live="polite" aria-busy="true">
        {#if direct.outils.length}
          <div class="outils">
            {#each direct.outils as o}<span class="etiquette">{o.nom}{o.detail ? ' · ' + o.detail.slice(0, 40) : ''}</span>{/each}
          </div>
        {/if}
        {#each segments(direct.texte, true) as s}
          {#if s.genre === 'texte'}<Markdown source={s.texte} />{:else}<div class="encart alerte">
              ✍️ Rédaction du fichier proposé…
            </div>{/if}
        {/each}
        <div class="secondaire attente">
          <span class="points" aria-hidden="true"><i></i><i></i><i></i></span>
          {direct.position > 0
            ? `En file d'attente (${direct.position} tour${direct.position > 1 ? 's' : ''} avant)`
            : direct.texte
              ? ''
              : "L'assistant réfléchit…"}
        </div>
      </div>
    {/if}
  </div>

  <footer class="saisie">
    {#if pieces.length}
      <div class="rangee" style="margin-bottom:6px">
        {#each pieces as p, i}
          <button class="etiquette accent" onclick={() => pieces.splice(i, 1)} aria-label={'Retirer ' + p.nom}>📎 {p.nom} ✕</button>
        {/each}
      </div>
    {/if}
    <div class="ligne">
      <input type="file" bind:this={fichier} onchange={joindre} accept="image/*,.pdf,.txt,.md,.cook" multiple hidden />
      <button class="btn icone" onclick={() => fichier.click()} disabled={!app.enLigne} aria-label="Joindre une photo ou un fichier"
        >📎</button
      >
      <textarea
        bind:this={champ}
        bind:value={saisie}
        rows="1"
        onkeydown={touche}
        onpaste={coller}
        placeholder={app.enLigne ? 'Écris ou colle une recette…' : 'Hors connexion'}
        disabled={!app.enLigne}
        aria-label="Message"></textarea>
      <button
        class="btn principal icone"
        onclick={() => envoyer()}
        disabled={occupe || !app.enLigne || (!saisie.trim() && !pieces.length)}
        aria-label="Envoyer">➤</button
      >
    </div>
  </footer>
</div>

{#if menu && discussion}
  <div class="voile" onclick={(e) => e.target === e.currentTarget && (menu = false)} role="presentation">
    <div class="feuille" role="dialog" aria-label="Options de la discussion">
      <h2>{discussion.titre}</h2>
      <label class="secondaire" for="modele">Modèle</label>
      <select
        id="modele"
        value={discussion.modele}
        onchange={(e) => modifier({ modele: e.target.value }, 'Modèle changé pour les prochains tours.')}
        style="margin-bottom:10px"
      >
        {#each sante?.modeles ?? [discussion.modele] as modele}<option value={modele}>{modele}</option>{/each}
      </select>
      <label class="secondaire" for="domaine">Domaine (préférences injectées)</label>
      <select
        id="domaine"
        value={discussion.domaine ?? ''}
        onchange={(e) => modifier({ domaine: e.target.value })}
        style="margin-bottom:14px"
      >
        <option value="">Aucun</option>
        {#each sante?.domaines ?? [] as domaine}<option value={domaine}>{domaine}</option>{/each}
      </select>
      <div class="secondaire" style="margin-bottom:12px">Coût estimé de la discussion : {euros(coutTotal)}</div>
      <button class="btn" onclick={renommer}>✏️ Renommer</button>
      <button class="btn" onclick={() => dupliquer()}>⧉ Dupliquer</button>
      <button class="btn" onclick={archiver}>🗄 {discussion.archivee ? 'Désarchiver' : 'Archiver'}</button>
      <button class="btn danger" onclick={supprimer}>🗑 Supprimer</button>
      <button class="btn discret" onclick={() => (menu = false)} style="justify-content:center">Fermer</button>
    </div>
  </div>
{/if}

<style>
  .fil {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .message {
    max-width: 100%;
  }
  .message.moi {
    align-self: flex-end;
    max-width: 88%;
  }
  .bulle {
    background: var(--accent-doux);
    padding: 10px 14px;
    border-radius: 16px 16px 4px 16px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .pieces {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
    margin-bottom: 6px;
  }
  .pieces img {
    max-width: 160px;
    max-height: 160px;
    border-radius: 12px;
    object-fit: cover;
  }
  .outils {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 8px;
  }
  .pied {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    margin-top: 6px;
    font-size: 0.78rem;
  }
  .lien {
    background: none;
    border: 0;
    color: var(--texte-2);
    text-decoration: underline;
    cursor: pointer;
    padding: 0;
    font-size: inherit;
  }
  .attente {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
    min-height: 24px;
  }
  .points {
    display: inline-flex;
    gap: 4px;
  }
  .points i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent);
    animation: pulse 1.2s infinite ease-in-out;
  }
  .points i:nth-child(2) {
    animation-delay: 0.2s;
  }
  .points i:nth-child(3) {
    animation-delay: 0.4s;
  }
  @keyframes pulse {
    0%,
    80%,
    100% {
      opacity: 0.25;
    }
    40% {
      opacity: 1;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .points i {
      animation: none;
    }
  }
  .saisie {
    border-top: 1px solid var(--bord);
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
    background: var(--surface);
    flex: none;
  }
  .saisie .ligne {
    display: flex;
    gap: 8px;
    align-items: flex-end;
  }
  .saisie textarea {
    flex: 1;
    max-height: 40dvh;
    field-sizing: content;
    min-height: 44px;
  }
</style>
