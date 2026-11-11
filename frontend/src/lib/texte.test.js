// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { colorerCook, diffLignes, markdown, segments } from './texte.js';

describe('segments', () => {
  it('découpe un message enregistré autour des marqueurs de proposition', () => {
    expect(segments('Avant\n\n[[proposition:12]]\n\nAprès')).toEqual([
      { genre: 'texte', texte: 'Avant\n\n' },
      { genre: 'proposition', id: 12 },
      { genre: 'texte', texte: '\n\nAprès' },
    ]);
  });

  it('masque le bloc brut pendant le streaming, complet ou non', () => {
    const complet = 'Voici.\n\n```proposition\ncible: recette\n---\nx\n```\n\nSuite';
    expect(segments(complet, true).map((s) => s.genre)).toEqual(['texte', 'redaction', 'texte']);
    const ouvert = 'Voici.\n\n```proposition\ncible: recette\n---\n@farine{250';
    expect(segments(ouvert, true).map((s) => s.genre)).toEqual(['texte', 'redaction']);
  });
});

describe('markdown', () => {
  it('assainit le HTML et enveloppe les tableaux', () => {
    const html = markdown('<script>alert(1)</script><img src=x onerror=alert(1)>\n\n| a | b |\n|---|---|\n| 1 | 2 |');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('onerror');
    expect(html).toContain('<div class="tableau"><table>');
  });

  it('ouvre les liens dans un nouvel onglet sans référent', () => {
    expect(markdown('[source](https://example.org)')).toContain('rel="noopener noreferrer"');
  });
});

describe('colorerCook', () => {
  it('échappe le texte avant de baliser', () => {
    const html = colorerCook('---\ntitle: <b>T</b>\n---\nMélanger @farine T45{250%g} dans #bol{} ~cuisson{20%minutes} <i>x</i>');
    expect(html).toContain('&lt;b&gt;T&lt;/b&gt;');
    expect(html).toContain('&lt;i&gt;x&lt;/i&gt;');
    expect(html).toContain('<span class="c-ing">@farine T45{250%g}</span>');
    expect(html).toContain('<span class="c-ust">#bol{}</span>');
    expect(html).toContain('<span class="c-min">~cuisson{20%minutes}</span>');
  });
});

describe('diffLignes', () => {
  it('marque les lignes ajoutées et retirées', () => {
    expect(diffLignes('a\nb\nc\n', 'a\nB\nc\n')).toEqual([
      { signe: ' ', texte: 'a' },
      { signe: '-', texte: 'b' },
      { signe: '+', texte: 'B' },
      { signe: ' ', texte: 'c' },
    ]);
  });
});
