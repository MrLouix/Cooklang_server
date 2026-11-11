// Parcours de bout en bout sur la PWA, serveur lancé avec AC_MOTEUR=factice.
//   AC_URL=http://127.0.0.1:8765 node e2e/parcours.cjs [dossier-captures]
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

const URL = process.env.AC_URL || 'http://127.0.0.1:8765';
const captures = process.argv[2];

(async () => {
  const navigateur = await chromium.launch();
  const contexte = await navigateur.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
  const page = await contexte.newPage();
  const erreurs = [];
  page.on('pageerror', (e) => erreurs.push(String(e)));
  page.on('console', (m) => m.type() === 'error' && erreurs.push(m.text()));
  page.on('dialog', (d) => d.accept(d.type() === 'prompt' ? 'Brioche renommée' : undefined));
  const photo = async (nom) => captures && page.screenshot({ path: `${captures}/${nom}.png` });

  // 1. Nouvelle discussion, message, proposition affichée en carte
  await page.goto(URL);
  await page.getByRole('button', { name: /Nouvelle discussion/ }).click();
  await page.getByLabel('Message').fill('Analyse ma brioche : 250 g de farine, 3 œufs, 125 g de beurre');
  await page.getByRole('button', { name: 'Envoyer' }).click();
  const carte = page.getByRole('region', { name: 'Proposition de fichier' });
  await carte.waitFor();
  await assert.doesNotReject(page.getByRole('heading', { name: 'Diagnostic' }).waitFor());
  assert.ok(await page.locator('.tableau table').count(), 'tableau Markdown rendu');
  assert.match(await carte.innerText(), /Brioche du dimanche\.cook/);
  await photo('1-chat-proposition');

  // 2. Enregistrer : la carte passe à « Enregistrée »
  await carte.getByRole('button', { name: 'Enregistrer' }).click();
  await carte.getByText('Enregistrée').waitFor();
  await photo('2-enregistree');

  // 3. Modification : diff ligne à ligne
  await page.getByLabel('Message').fill('modifie ma brioche avec plus de sucre');
  await page.getByRole('button', { name: 'Envoyer' }).click();
  const seconde = page.getByRole('region', { name: 'Proposition de fichier' }).nth(1);
  await seconde.waitFor();
  assert.match(await seconde.locator('pre.diff').innerText(), /\+ .*35%g/);
  await photo('3-diff');
  await seconde.getByRole('button', { name: 'Ignorer' }).click();
  await seconde.getByText('Ignorée').waitFor();

  // 4. Renommer, puis retrouver la discussion dans la liste avec sa recette liée
  await page.getByRole('button', { name: 'Options de la discussion' }).click();
  await photo('4-options');
  await page.getByRole('button', { name: /Renommer/ }).click();
  await page.getByRole('link', { name: 'Retour aux discussions' }).click();
  const element = page.locator('.element').first();
  await element.waitFor();
  assert.match(await element.innerText(), /Brioche renommée[\s\S]*Brioche du dimanche/);
  await photo('5-discussions');

  // 5. Recettes : catégorie, contenu, historique, discussion liée
  await page.getByRole('link', { name: 'Recettes' }).click();
  await page.getByText('Brioche du dimanche').click();
  await page.locator('pre.cook .c-ing').first().waitFor();
  await photo('6-recette');
  await page.getByRole('button', { name: /Historique \(1\)/ }).click();
  await page.getByText('Version actuelle').waitFor();
  await page.getByRole('button', { name: /Discussions \(1\)/ }).click();
  await page.getByText('Brioche renommée').waitFor();

  // 6. Paramètres : changer « Œufs », la consigne est enregistrée
  await page.getByRole('link', { name: 'Retour aux recettes' }).click();
  await page.getByRole('link', { name: 'Paramètres' }).click();
  await page.getByLabel('Œufs').selectOption('grammes');
  await page.getByText(/Enregistré — appliqué/).waitFor();
  const parametres = await (await page.request.get(`${URL}/api/parametres`)).json();
  assert.equal(parametres.valeurs.oeufs, 'grammes');
  await photo('7-parametres');

  // 7. Base documentaire : créer une fiche depuis le gabarit
  await page.getByRole('link', { name: 'Références' }).click();
  await page.getByLabel('Nom de la nouvelle fiche').fill('brioche');
  await page.getByRole('button', { name: 'Créer' }).click();
  await page.getByRole('button', { name: 'Enregistrer' }).click();
  await page.getByRole('button', { name: /Fiches \(1\)/ }).waitFor();
  await photo('8-references');

  // 8. Système : crédit, mémoire, synchro
  await page.getByRole('link', { name: 'Système' }).click();
  await page.getByText('Crédit du mois').waitFor();
  await photo('9-systeme');
  await page.getByRole('button', { name: 'Mémoire' }).click();
  await page.getByText('materiel.md').waitFor();
  await page.getByRole('button', { name: 'Sombre' }).isHidden();

  // 9. Hors connexion : bandeau, envoi désactivé
  await page.getByRole('link', { name: 'Discussions' }).click();
  await page.locator('.element').first().click();
  await page.getByLabel('Message').waitFor();
  await contexte.setOffline(true);
  await page.getByText(/Hors connexion — consultation seule/).waitFor();
  assert.ok(await page.getByLabel('Message').isDisabled());
  await photo('10-hors-ligne');
  await contexte.setOffline(false);

  const utiles = erreurs.filter((e) => !/ERR_INTERNET_DISCONNECTED|Failed to load resource/.test(e));
  assert.deepEqual(utiles, [], 'aucune erreur JavaScript');
  await navigateur.close();
  console.log('Parcours complet : OK');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
