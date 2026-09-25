// Based on https://noumenal.es/notes/tailwind/django-integration/
// Loaded from input.css via @config. Asks Django (manage.py list_templates)
// for every template file and uses that list as Tailwind's content.
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

// upstage/ — the directory containing manage.py.
const projectRoot = path.resolve(__dirname, '../../..');

// Use the project's virtualenv Python so it works without activating the venv.
const getPython = () => {
  const venv = process.env.VIRTUAL_ENV || path.resolve(projectRoot, '../.venv');
  const candidates = [
    path.join(venv, 'Scripts', 'python.exe'), // Windows
    path.join(venv, 'bin', 'python'),         // macOS / Linux
  ];
  return candidates.find((p) => fs.existsSync(p)) || 'python';
};

// Function to execute the Django management command and capture its output
const getTemplateFiles = () => {
  const result = spawnSync(getPython(), ['manage.py', 'list_templates'], { cwd: projectRoot });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    console.log(result.stdout.toString(), result.stderr.toString());
    throw new Error(`Django management command exited with code ${result.status}`);
  }

  return result.stdout.toString()
    .split('\n')
    .map((file) => file.trim())
    .filter(Boolean)  // Remove empty strings, including last empty line.
    .map((file) => file.replace(/\\/g, '/'));  // Globs need forward slashes on Windows.
};

module.exports = {
  // Allow configuring some folders manually, and then concatenate with the
  // output of the Django management command.
  content: [].concat(getTemplateFiles()),
  theme: {
    extend: {},
  },
  plugins: [],
};
