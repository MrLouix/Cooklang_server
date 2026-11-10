// Valide un fichier Cooklang lu sur l'entrée standard et renvoie un JSON :
// { rapport, metadonnees, ingredients, ustensiles, minuteurs, etapes }
import { CooklangParser } from '@cooklang/cooklang';

let source = '';
process.stdin.setEncoding('utf8');
for await (const bloc of process.stdin) source += bloc;

const nombre = (v) => (typeof v === 'bigint' ? Number(v) : v);
try {
  const [recette, rapport] = new CooklangParser().parse(source);
  let etapes = 0;
  for (const section of recette.sections ?? []) {
    for (const element of section.content ?? []) if (element.type === 'step') etapes += 1;
  }
  const sortie = {
    rapport: rapport ?? '',
    metadonnees: {
      title: recette.title ?? null,
      course: recette.course ?? null,
      servings: recette.servings ?? null,
      source: recette.source ?? null,
    },
    ingredients: (recette.ingredients ?? []).map((i) => ({
      nom: i.name,
      optionnel: String(i.modifiers ?? '').includes('OPT'),
      quantite: i.quantity?.value?.value?.value ?? null,
      unite: i.quantity?.unit ?? null,
    })),
    ustensiles: (recette.cookware ?? []).map((c) => c.name),
    minuteurs: (recette.timers ?? []).length,
    etapes,
  };
  process.stdout.write(JSON.stringify(sortie, (_, v) => nombre(v)));
} catch (erreur) {
  process.stdout.write(JSON.stringify({ exception: String(erreur?.message ?? erreur) }));
}
