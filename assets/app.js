// Restreindre Nominatim côté front (mêmes bornes que le serveur)
const NOMINATIM_CFG = {
  countrycodes: 'fr',
  // viewbox: [left, top, right, bottom]
  viewbox: [3.75, 43.72, 4.05, 43.53],
  bounded: 1
};

// --- Base Leaflet + chargement des données ---
const map = L.map('map', { scrollWheelZoom: true }).setView([43.61, 3.88], 11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

let allMarkers = [];
let layerGroup = L.layerGroup().addTo(map);
let DATA = []; // jeu de données courant

// Nouveaux: écriture CSV locale & options
let csvFileHandle = null;
const DEFAULT_CITY_HINT = "Montpellier, France";
const AUTOGEOCODE_ON_LOAD = false;

function priceIcon(price) {
  const label = (price == null || price === '') ? '— €' : `${Number(price).toLocaleString('fr-FR')} €`;
  const html = `<div class="price-badge">${label}</div>`;
  return L.divIcon({ html, className: '', iconSize: [60, 24], iconAnchor: [30, 12] });
}

function render(data) {
  layerGroup.clearLayers();
  allMarkers = [];

  const maxRent = Number(document.getElementById('maxRent').value || Infinity);
  const typeFilter = document.getElementById('typeFilter').value.trim().toUpperCase();
  const parking = document.getElementById('parkingFilter').value;

  const unlocated = [];

  data.forEach(item => {
    const hasCoords = isFiniteNum(item.latitude) && isFiniteNum(item.longitude);
    if (!hasCoords) unlocated.push(item);
    if (!hasCoords) return;

    if (isFinite(maxRent) && item.loyer != null && Number(item.loyer) > maxRent) return;
    if (typeFilter && (String(item.type || '').toUpperCase() !== typeFilter)) return;
    if (parking && (String(item.parking || '').toLowerCase() !== parking)) return;

    const marker = L.marker([Number(item.latitude), Number(item.longitude)], { icon: priceIcon(item.loyer) });
    const title = [
      item.type || '',
      (item.surface_m2 != null ? `${item.surface_m2} m²` : null),
      (item.chambres != null ? `${item.chambres} ch.` : null)
    ].filter(Boolean).join(' – ');

    const addr = item.adresse || '';
    const extra = item.label ? `<div>${escapeHtml(item.label)}</div>` : '';
    const ce = (item.cuisine_equipee || '').toLowerCase();
    const park = (item.parking || '').toLowerCase();
    const url = item.url ? `<a class="btn" target="_blank" rel="noopener" href="${escapeAttr(item.url)}">Voir l'annonce</a>` : '';

    marker.bindPopup(`
      <h3>${(item.loyer != null) ? Number(item.loyer).toLocaleString('fr-FR') + ' €' : '— €'}</h3>
      <p><strong>${escapeHtml(title || '—')}</strong></p>
      <p>${escapeHtml(addr || '—')}</p>
      ${extra}
      <p>Parking: <strong>${escapeHtml(park || '—')}</strong> &nbsp;|&nbsp; Cuisine équipée: <strong>${escapeHtml(ce || '—')}</strong></p>
      ${url}
    `);
    marker.addTo(layerGroup);
    allMarkers.push(marker);
  });

  if (allMarkers.length) {
    const group = L.featureGroup(allMarkers);
    map.fitBounds(group.getBounds().pad(0.2));
  }

  updateUnlocatedList(unlocated);
}

function updateUnlocatedList(list) {
  const cont = document.getElementById('unlocList');
  const count = document.getElementById('unlocCount');
  if (count) count.textContent = String(list.length);

  if (!cont) return;
  if (!list.length) {
    cont.innerHTML = `<div class="muted">Aucune entrée non localisée.</div>`;
    return;
  }

  cont.innerHTML = list.map((r) => {
    const price = (r.loyer != null) ? `${Number(r.loyer).toLocaleString('fr-FR')} €` : '— €';
    const addr = r.adresse || '—';
    const tpe = r.type || '—';
    const ch = (r.chambres != null) ? r.chambres : '—';
    const surf = (r.surface_m2 != null) ? r.surface_m2 + ' m²' : '—';
    return `<div class="list-row">
      <div><b>${price}</b></div>
      <div>${escapeHtml(addr)}</div>
      <div>${escapeHtml(tpe)}, ${ch} ch., ${surf}</div>
      <div>${r.url ? `<a href="${escapeAttr(r.url)}" target="_blank" rel="noopener">Annonce</a>` : ''}</div>
    </div>`;
  }).join('');
}

async function loadData() {
  try {
    const res = await fetch('data/apartments.json?v=' + Date.now(), { cache: 'no-store' });
    const data = await res.json();
    DATA = Array.isArray(data) ? data : [];
  } catch (e) {
    DATA = [];
  }

  if (AUTOGEOCODE_ON_LOAD) {
    await autogeocodeMissing();
  }

  render(DATA);
}
loadData();

// Filtres
document.getElementById('resetBtn').addEventListener('click', () => {
  document.getElementById('maxRent').value = '';
  document.getElementById('typeFilter').value = '';
  document.getElementById('parkingFilter').value = '';
  render(DATA);
});

// Ajout d'un appartement (tous champs optionnels)
const addForm = document.getElementById('addForm');
const addStatus = document.getElementById('addStatus');

if (addForm) {
  addForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (addStatus) addStatus.textContent = 'Ajout en cours…';

    const formData = new FormData(addForm);
    let item = {
      loyer: toInt(formData.get('loyer')),
      adresse: str(formData.get('adresse')) || null,
      cuisine_equipee: str(formData.get('cuisine_equipee')) || null,
      type: str(formData.get('type')) || null,
      parking: str(formData.get('parking')) || null,
      chambres: toInt(formData.get('chambres')),
      surface_m2: toFloat(formData.get('surface_m2')),
      url: str(formData.get('url')) || null,
      label: str(formData.get('label')) || null,
      latitude: toFloat(formData.get('latitude')),
      longitude: toFloat(formData.get('longitude')),
    };

    // Géocodage si lat/lon manquants → adresse puis label + ville
    if (!isFiniteNum(item.latitude) || !isFiniteNum(item.longitude)) {
      let query = item.adresse && item.adresse.trim() ? item.adresse.trim() : null;
      if (!query && item.label && item.label.trim()) {
        query = `${item.label.trim()}, ${DEFAULT_CITY_HINT}`;
      }
      if (query) {
        try {
          const geocoded = await geocodeAddress(query);
          if (geocoded) {
            item.latitude = geocoded.lat;
            item.longitude = geocoded.lon;
          }
        } catch {}
      }
    }

    // Ajout et rendu
    DATA.push(item);
    render(DATA);

    // Auto-save CSV si lié
    if (csvFileHandle) {
      try { await saveCsvToLinkedFile(); } catch {}
    }

    // Reset + message
    addForm.reset();
    if (addStatus) {
      addStatus.textContent = '✓ Ajouté. ';
      if (!isFiniteNum(item.latitude) || !isFiniteNum(item.longitude)) {
        addStatus.textContent += 'Sans coordonnées, la fiche reste dans "Entrées non localisées". ';
      }
      if (!csvFileHandle) {
        addStatus.textContent += 'Astuce : liez votre CSV pour enregistrer sans téléchargement.';
      }
      setTimeout(() => (addStatus.textContent = ''), 5000);
    }
  });
}

// ---------- File System Access API : lier et écrire le CSV ----------
document.getElementById('linkCsvBtn').addEventListener('click', linkCsvFile);
document.getElementById('saveCsvBtn').addEventListener('click', () => saveCsvToLinkedFile().catch(() => {}));

async function linkCsvFile() {
  if (!('showOpenFilePicker' in window)) {
    alert("Votre navigateur ne permet pas l'écriture directe de fichiers. Utilisez Exporter CSV.");
    return;
  }
  try {
    const [handle] = await window.showOpenFilePicker({
      types: [{ description: 'CSV', accept: { 'text/csv': ['.csv'] } }],
      multiple: false
    });
    const ok = await verifyPermission(handle, true);
    if (!ok) throw new Error('Permission refusée');
    csvFileHandle = handle;
    document.getElementById('saveCsvBtn').disabled = false;
    setFileStatus(`CSV lié : ${handle.name}`);
  } catch (err) {
    setFileStatus('Aucun fichier lié');
  }
}

async function saveCsvToLinkedFile() {
  if (!csvFileHandle) {
    alert('Aucun fichier CSV lié.');
    return;
  }
  const csv = toCSV(DATA);
  const writable = await csvFileHandle.createWritable();
  await writable.write(csv);
  await writable.close();
  setFileStatus('CSV enregistré ✔︎');
}

async function verifyPermission(fileHandle, write = false) {
  const opts = write ? { mode: 'readwrite' } : {};
  if ((await fileHandle.queryPermission(opts)) === 'granted') return true;
  if ((await fileHandle.requestPermission(opts)) === 'granted') return true;
  return false;
}

function setFileStatus(msg) {
  const el = document.getElementById('fileStatus');
  if (el) el.textContent = msg;
}

// ---------- Auto-géocodage optionnel au chargement ----------
async function autogeocodeMissing() {
  for (const item of DATA) {
    const hasCoords = isFiniteNum(item.latitude) && isFiniteNum(item.longitude);
    if (hasCoords) continue;
    let query = (item.adresse && item.adresse.trim()) ? item.adresse.trim() : null;
    if (!query && item.label && item.label.trim()) {
      query = `${item.label.trim()}, ${DEFAULT_CITY_HINT}`;
    }
    if (!query) continue;
    const geo = await geocodeAddress(query);
    if (geo) {
      item.latitude = geo.lat;
      item.longitude = geo.lon;
      await new Promise(r => setTimeout(r, 1100)); // 1 req/s pour Nominatim
    }
  }
}

// ---------- Utilitaires ----------
async function geocodeAddress(q) {
  const params = new URLSearchParams({
    format: 'jsonv2',
    'accept-language': 'fr',
    countrycodes: NOMINATIM_CFG.countrycodes,
    bounded: String(NOMINATIM_CFG.bounded),
    viewbox: NOMINATIM_CFG.viewbox.join(',')
  });
  const url = `https://nominatim.openstreetmap.org/search?${params.toString()}&q=${encodeURIComponent(q)}`;
  const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
  if (!res.ok) return null;
  const arr = await res.json();
  if (Array.isArray(arr) && arr.length) {
    const { lat, lon } = arr[0];
    return { lat: Number(lat), lon: Number(lon) };
  }
  return null;
}

function toInt(v) {
  if (v == null || v === '') return null;
  const n = parseInt(String(v).replace(',', '.').trim(), 10);
  return Number.isFinite(n) ? n : null;
}
function toFloat(v) {
  if (v == null || v === '') return null;
  const n = parseFloat(String(v).replace(',', '.').trim());
  return Number.isFinite(n) ? n : null;
}
function str(v) {
  const s = (v ?? '').toString().trim();
  return s.length ? s : '';
}
function isFiniteNum(v) {
  return typeof v === 'number' && Number.isFinite(v);
}
function escapeHtml(s) {
  return (s ?? '').toString()
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function escapeAttr(s) {
  return escapeHtml(s).replace(/"/g, '&quot;');
}

// Exports fallback
document.getElementById('exportCsvBtn').addEventListener('click', () => {
  const csv = toCSV(DATA);
  downloadFile('apartments.csv', 'text/csv;charset=utf-8;', csv);
});
document.getElementById('exportJsonBtn').addEventListener('click', () => {
  const json = JSON.stringify(DATA, null, 2);
  downloadFile('apartments.json', 'application/json;charset=utf-8;', json);
});

function toCSV(rows) {
  const headers = ["loyer","adresse","cuisine_equipee","type","parking","chambres","surface_m2","url","label","latitude","longitude"];
  const escape = (val) => {
    if (val == null) return '';
    const s = String(val);
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [headers.join(",")];
  for (const r of rows) {
    lines.push(headers.map(h => escape(r[h])).join(","));
  }
  return lines.join("\n");
}

function downloadFile(filename, mime, content) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Ouvre un nouvel Issue prérempli avec le contenu du dernier formulaire saisi.
// L’Action GitHub lira ce YAML et mettra à jour data/apartments.csv + apartments.json.
const sendToGitHubBtn = document.getElementById('sendToGitHubBtn');
let sendingLock = false;

if (sendToGitHubBtn) {
  sendToGitHubBtn.addEventListener('click', async () => {
    if (sendingLock) return;
    sendingLock = true;
    setTimeout(() => (sendingLock = false), 1200); // anti double-clic 1,2s

    const cfg = window.APP_CONFIG || {};
    if (!cfg.owner || !cfg.repo) {
      alert("Config GitHub manquante (assets/config.js).");
      return;
    }

    const formData = new FormData(document.getElementById('addForm'));
    const row = {
      loyer: val(formData.get('loyer')),
      adresse: val(formData.get('adresse')),
      cuisine_equipee: val(formData.get('cuisine_equipee')),
      type: val(formData.get('type')),
      parking: val(formData.get('parking')),
      chambres: val(formData.get('chambres')),
      surface_m2: val(formData.get('surface_m2')),
      url: val(formData.get('url')),
      label: val(formData.get('label')),
      latitude: val(formData.get('latitude')),
      longitude: val(formData.get('longitude')),
    };

    const title = `Nouvel appartement: ${row.adresse || row.label || '(sans adresse)'}`;

    const yaml = [
      '```yaml',
      `loyer: ${row.loyer || ''}`,
      `adresse: ${row.adresse || ''}`,
      `cuisine_equipee: ${row.cuisine_equipee || ''}`,
      `type: ${row.type || ''}`,
      `parking: ${row.parking || ''}`,
      `chambres: ${row.chambres || ''}`,
      `surface_m2: ${row.surface_m2 || ''}`,
      `url: ${row.url || ''}`,
      `label: ${row.label || ''}`,
      `latitude: ${row.latitude || ''}`,
      `longitude: ${row.longitude || ''}`,
      '```',
      '',
      '_Issue généré depuis GitHub Pages._'
    ].join('\n');

    // Si tu veux garder ton label “Appartements”, laisse-le ici :
    const labels = encodeURIComponent('Appartements');

    const url = `https://github.com/${encodeURIComponent(cfg.owner)}/${encodeURIComponent(cfg.repo)}` +
                `/issues/new?title=${encodeURIComponent(title)}&labels=${labels}&body=${encodeURIComponent(yaml)}`;

    window.open(url, '_blank', 'noopener');
  });
}

function val(v) {
  const s = (v ?? '').toString().trim();
  return s.length ? s : '';

}



