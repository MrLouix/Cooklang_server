import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';

export default [
  { ignores: ['dist/', 'node_modules/'] },
  js.configs.recommended,
  ...svelte.configs['flat/recommended'],
  ...svelte.configs['flat/prettier'],
  { languageOptions: { globals: { ...globals.browser } } },
  { files: ['public/sw.js'], languageOptions: { globals: { ...globals.serviceworker } } },
  { files: ['e2e/**', '*.config.js'], languageOptions: { globals: { ...globals.node } } },
  {
    rules: {
      // Le HTML injecté est assaini (DOMPurify) ou entièrement échappé avant balisage : voir lib/texte.js.
      'svelte/no-at-html-tags': 'off',
      // Routage par ancre (#/…) : pas de resolve() à appliquer.
      'svelte/no-navigation-without-resolve': 'off',
      // Les listes qui changent (messages, discussions, sources) sont indexées par clé ; les autres sont statiques.
      'svelte/require-each-key': 'off',
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
];
