<script>
  import { diffLignes } from '../lib/texte.js';
  let { avant, apres } = $props();
  const lignes = $derived(diffLignes(avant, apres));
  const ajouts = $derived(lignes.filter((l) => l.signe === '+').length);
  const retraits = $derived(lignes.filter((l) => l.signe === '-').length);
</script>

<div class="secondaire" style="margin-bottom:6px">
  <span class="etiquette ok">+{ajouts}</span> <span class="etiquette danger">−{retraits}</span> ligne(s)
</div>
<pre class="diff" aria-label="Différences ligne à ligne">{#each lignes as ligne}<span class:plus={ligne.signe === '+'} class:moins={ligne.signe === '-'}>{ligne.signe} {ligne.texte}</span>{/each}</pre>
