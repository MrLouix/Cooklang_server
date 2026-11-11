<script>
  import { markdown } from '../lib/texte.js';
  let { source } = $props();
</script>

<!-- HTML assaini par DOMPurify dans lib/texte.js -->
<div class="md">{@html markdown(source)}</div>
