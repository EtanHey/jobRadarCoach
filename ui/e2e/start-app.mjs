// Reuse the repository's synthetic copy pattern; mutate only the disposable copy.
import { spawn } from 'node:child_process';
import { mkdir, rm, writeFile, readFile, readdir } from 'node:fs/promises';
import { resolve } from 'node:path';
await writeFile('next-env.d.ts', '/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n', { flag: 'wx' }).catch(error => { if (error.code !== 'EEXIST') throw error; });
const output = resolve('.e2e/app');
await mkdir(output, { recursive: true });
await rm(resolve(output, 'fixture-app'), { recursive: true, force: true });
await new Promise((ok, fail) => {
  const child = spawn(process.execPath, ['scripts/prepare-globe-fixture.mjs'], { stdio: 'inherit', env: { ...process.env, GLOBE_QA_OUTPUT: output } });
  child.on('exit', code => code === 0 ? ok() : fail(new Error(`prepare: ${code}`)));
});
const target = resolve(output, 'fixture-app');
// No server-side production API or login code is reachable from the fixture app.
for (const entry of await readdir(resolve(target, 'app'), { withFileTypes: true })) {
  if (entry.isDirectory()) await rm(resolve(target, 'app', entry.name), { recursive: true, force: true });
}
await writeFile(resolve(target, 'next.config.ts'), `export default { turbopack: { root: ${JSON.stringify(resolve('.'))} }, allowedDevOrigins: ['127.0.0.1'], devIndicators: false };`);
const cssPath = resolve(target, 'app/globals.css');
await writeFile(cssPath, (await readFile(cssPath, 'utf8')).replace('@import "tailwindcss";', '@import "tailwindcss" source(none);\n@source "../components";\n@source "../app";'));
const mutations = {
  drawer: ['components/job-drawer.tsx', 'initialFocus={() => document.querySelector<HTMLElement>("[data-job-description]")}', 'initialFocus={false}'],
  status: ['components/job-board.tsx', 'await mutateStatus({ id, patch });', 'await mutateStatus({ id, patch }); requestRefresh();'],
  delayed: ['components/job-board.tsx', 'await mutateStatus({ id, patch });', 'await mutateStatus({ id, patch }); setTimeout(requestRefresh, 1500);'],
  pill: ['components/new-roles-pill.tsx', 'notice && <button', 'false && <button'],
  hidden: ['components/job-board.tsx', 'countNewRoleCards(jobs, newRoles.jobs, view)', 'newRoles.jobs.length'],
};
const mutation = process.env.JRC_E2E_MUTATION;
if (mutation) {
  if (!Object.hasOwn(mutations, mutation)) throw new Error('Unknown pilot mutation');
  const [file, before, after] = mutations[mutation];
  const path = resolve(target, file), source = await readFile(path, 'utf8');
  if (source.split(before).length !== 2) throw new Error(`Mutation ${mutation} does not match exactly once`);
  await writeFile(path, source.replace(before, after));
}
const child = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev', target, '--hostname', '127.0.0.1', '--port', process.argv[2]], { stdio: 'inherit' });
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
child.on('exit', code => process.exit(code ?? 1));
