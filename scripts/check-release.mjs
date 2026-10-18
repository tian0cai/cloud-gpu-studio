import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
const lock = JSON.parse(fs.readFileSync('package-lock.json', 'utf8'));
const config = JSON.parse(fs.readFileSync('src-tauri/tauri.conf.json', 'utf8'));
const cargo = fs.readFileSync('src-tauri/Cargo.toml', 'utf8');
const cargoVersion = cargo.match(/\[package\][\s\S]*?\nversion = "([^"]+)"/)?.[1];
const cargoLockVersion = fs.readFileSync('src-tauri/Cargo.lock', 'utf8').match(/\[\[package\]\]\nname = "cloud-gpu-studio"\nversion = "([^"]+)"/)?.[1];
if ([lock.version, lock.packages[''].version, config.version, cargoVersion, cargoLockVersion].some(v => v !== pkg.version)) throw new Error('Version mismatch across package, lockfiles, Tauri config, and Cargo.');
const expectedLicense = 'GPL-3.0-or-later';
if (pkg.license !== expectedLicense || lock.packages[''].license !== expectedLicense || !cargo.includes(`license = "${expectedLicense}"`)) throw new Error('Project license metadata must match GPL-3.0-or-later.');
const gpl = fs.readFileSync('LICENSE', 'utf8');
if (!gpl.includes('GNU GENERAL PUBLIC LICENSE') || !gpl.includes('Version 3, 29 June 2007') || fs.readFileSync('outputs/cloud-gpu-studio/comfyui_cloud_bridge/LICENSE', 'utf8') !== gpl) throw new Error('Application and ComfyUI bridge must include the complete GPLv3 text.');
if (!fs.readFileSync('outputs/cloud-gpu-studio/comfyui_cloud_bridge/__init__.py', 'utf8').startsWith(`# SPDX-License-Identifier: ${expectedLicense}`)) throw new Error('ComfyUI bridge SPDX identifier must match the project license.');
if (!config.bundle.createUpdaterArtifacts || !config.plugins?.updater?.pubkey || !config.plugins?.updater?.endpoints?.length) throw new Error('Updater is not fully configured.');
for (const source of Object.keys(config.bundle.resources)) {
  if (!fs.existsSync(`src-tauri/${source}`)) throw new Error(`Missing bundle resource: ${source}`);
  if (/smoke|__pycache__|\.mp4$|\.png$/i.test(source)) throw new Error(`Private or test media in bundle: ${source}`);
}
const tracked = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard'], { encoding: 'utf8' }).trim().split('\n').filter(Boolean);
const forbidden = tracked.filter(path => /(^|\/)(work|node_modules|dist|target|__pycache__)(\/|$)|-smoke\.(png|mp4)$|\.key$|\.pem$|\.env(?:\.|$)/i.test(path));
if (forbidden.length) throw new Error(`Private or generated tracked files:\n${forbidden.join('\n')}`);
for (const path of tracked.filter(path => /\.(ts|rs|py|json|sh|md|yml|yaml)$/.test(path))) {
  const body = fs.readFileSync(path, 'utf8');
  if (/rpa_[A-Za-z0-9]{25,}|(?<![A-Za-z0-9])[a-f0-9]{64}(?![A-Za-z0-9])/.test(body) && !path.endsWith('.lock.json')) {
    throw new Error(`Potential credential or private key in ${path}; review before publishing.`);
  }
}
console.log(`Release checks passed for v${pkg.version}. ${Object.keys(config.bundle.resources).length} explicit bundle resources.`);
