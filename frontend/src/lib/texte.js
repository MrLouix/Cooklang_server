// Rendu du texte : Markdown assaini, découpage des propositions, coloration Cooklang, dates.
import DOMPurify from 'dompurify';
import { diffLines } from 'diff';
import { marked } from 'marked';

marked.setOptions({ gfm: true, breaks: false });

DOMPurify.addHook('afterSanitizeAttributes', (noeud) => {
  if (noeud.tagName === 'A') {
    noeud.setAttribute('target', '_blank');
    noeud.setAttribute('rel', 'noopener noreferrer');
  }
});

/** Markdown → HTML sûr. Les tableaux sont enveloppés pour défiler horizontalement sur téléphone (F-3). */
export function markdown(source) {
  const html = DOMPurify.sanitize(marked.parse(source || ''), { FORBID_TAGS: ['style', 'form', 'input', 'iframe'] });
  return html.replaceAll('<table>', '<div class="tableau"><table>').replaceAll('</table>', '</table></div>');
}

const MARQUEUR = /\[\[proposition:(\d+)\]\]/g;
const BLOC_COMPLET = /^(`{3,})proposition[ \t]*\n[\s\S]*?^\1[ \t]*$/gm;
const BLOC_OUVERT = /^`{3,}proposition[\s\S]*$/m;

/**
 * Découpe un message en segments : { genre: 'texte', texte } | { genre: 'proposition', id } | { genre: 'redaction' }.
 * Pendant le streaming, les blocs `proposition` bruts sont masqués derrière un indicateur de rédaction.
 */
export function segments(contenu, enCours = false) {
  let texte = contenu || '';
  const sortie = [];
  if (enCours) {
    texte = texte.replace(BLOC_COMPLET, '\u0000');
    texte = texte.replace(BLOC_OUVERT, '\u0000');
    for (const [i, morceau] of texte.split('\u0000').entries()) {
      if (i > 0) sortie.push({ genre: 'redaction' });
      if (morceau.trim()) sortie.push({ genre: 'texte', texte: morceau });
    }
    return sortie;
  }
  let dernier = 0;
  for (const trouve of texte.matchAll(MARQUEUR)) {
    const avant = texte.slice(dernier, trouve.index);
    if (avant.trim()) sortie.push({ genre: 'texte', texte: avant });
    sortie.push({ genre: 'proposition', id: Number(trouve[1]) });
    dernier = trouve.index + trouve[0].length;
  }
  const reste = texte.slice(dernier);
  if (reste.trim()) sortie.push({ genre: 'texte', texte: reste });
  return sortie;
}

const echapper = (t) => t.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');

/** Coloration simple d'un fichier Cooklang (ou Markdown : rendu tel quel, échappé). */
export function colorerCook(source) {
  let dansEntete = false;
  let dansBloc = false;
  return (source || '')
    .split('\n')
    .map((brute, numero) => {
      const ligne = echapper(brute);
      if (brute.trim() === '---' && (numero === 0 || dansEntete)) {
        dansEntete = numero === 0;
        return `<span class="c-meta">${ligne}</span>`;
      }
      if (dansEntete) return ligne.replace(/^([\w.]+)(:)/, '<span class="c-cle">$1</span>$2');
      if (dansBloc || brute.includes('[-')) {
        dansBloc = !brute.includes('-]');
        return `<span class="c-comm">${ligne}</span>`;
      }
      if (brute.startsWith('>')) return `<span class="c-note">${ligne}</span>`;
      if (/^==.*/.test(brute)) return `<span class="c-section">${ligne}</span>`;
      return ligne
        .replace(/@\??(?:[^@#~{}\n]*?\{[^}]*\}|[\p{L}\p{N}_-]+)/gu, '<span class="c-ing">$&</span>')
        .replace(/#(?:[^@#~{}\n]*?\{[^}]*\}|[\p{L}\p{N}_-]+)/gu, '<span class="c-ust">$&</span>')
        .replace(/~[^@#~{}\n]*?\{[^}]*\}/gu, '<span class="c-min">$&</span>');
    })
    .join('\n');
}

/** Diff ligne à ligne : [{ signe: '+' | '-' | ' ', texte }]. */
export function diffLignes(avant, apres) {
  const lignes = [];
  for (const partie of diffLines(avant || '', apres || '')) {
    const signe = partie.added ? '+' : partie.removed ? '-' : ' ';
    for (const texte of partie.value.replace(/\n$/, '').split('\n')) lignes.push({ signe, texte });
  }
  return lignes;
}

const jour = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' });
const heure = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' });
const complet = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });

export function dateCourte(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const auj = new Date();
  if (d.toDateString() === auj.toDateString()) return heure.format(d);
  return jour.format(d) + (d.getFullYear() !== auj.getFullYear() ? ` ${d.getFullYear()}` : '');
}

export const dateComplete = (iso) => (iso ? complet.format(new Date(iso)) : '');
export const euros = (montant) =>
  `${Number(montant || 0)
    .toFixed(2)
    .replace('.', ',')} $`;
