import fs from 'node:fs';

const version = process.argv[2];
if (!version || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/.test(version)) {
  console.error('Usage: npm run version:set -- 0.2.0');
  process.exit(1);
}
for (const filename of ['package.json', 'package-lock.json']) {
  const data = JSON.parse(fs.readFileSync(filename, 'utf8'));
  data.version = version;
  if (filename === 'package-lock.json') data.packages[''].version = version;
  fs.writeFileSync(filename, `${JSON.stringify(data, null, 2)}\n`);
}
const configFile = 'src-tauri/tauri.conf.json';
const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
config.version = version;
fs.writeFileSync(configFile, `${JSON.stringify(config, null, 2)}\n`);
const cargoFile = 'src-tauri/Cargo.toml';
const cargo = fs.readFileSync(cargoFile, 'utf8').replace(/(\[package\][\s\S]*?\nversion = ")[^"]+(")/, (_, first, last) => `${first}${version}${last}`);
fs.writeFileSync(cargoFile, cargo);
const cargoLockFile = 'src-tauri/Cargo.lock';
const cargoLock = fs.readFileSync(cargoLockFile, 'utf8').replace(/(\[\[package\]\]\nname = "cloud-gpu-studio"\nversion = ")[^"]+(")/, (_, first, last) => `${first}${version}${last}`);
fs.writeFileSync(cargoLockFile, cargoLock);
console.log(`Version set to ${version}. Run release:check, then commit these files before publishing.`);
