(function () {
  const root = document.getElementById('job-preview-root');
  if (!root || !window.React || !window.ReactDOM || !window.maplibregl) return;

  const e = React.createElement;
  const jobId = root.dataset.jobId;
  const outputUrl = root.dataset.outputUrl;
  const jobsUrl = root.dataset.jobsUrl;
  const PAGE_SIZE = 25;

  const tileStyle = {
    version: 8,
    sources: {
      osm: {
        type: 'raster',
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        attribution: 'OpenStreetMap contributors'
      }
    },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }]
  };

  function fetchJson(url, options) {
    return fetch(url, options).then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Request failed');
      return data;
    });
  }

  function usePreviewMap(features, bbox) {
    const mapRef = React.useRef(null);

    React.useEffect(() => {
      if (mapRef.current) return;
      mapRef.current = new maplibregl.Map({
        container: 'job-preview-map',
        style: tileStyle,
        center: [0, 20],
        zoom: 1.4
      });
      mapRef.current.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
    }, []);

    React.useEffect(() => {
      const map = mapRef.current;
      if (!map) return;

      const render = () => {
        const source = map.getSource('preview-features');
        const collection = features || { type: 'FeatureCollection', features: [] };
        if (source) {
          source.setData(collection);
        } else {
          map.addSource('preview-features', { type: 'geojson', data: collection });
          map.addLayer({
            id: 'preview-fill',
            type: 'fill',
            source: 'preview-features',
            paint: { 'fill-color': '#14b8a6', 'fill-opacity': 0.24 },
            filter: ['==', ['geometry-type'], 'Polygon']
          });
          map.addLayer({
            id: 'preview-line',
            type: 'line',
            source: 'preview-features',
            paint: { 'line-color': '#be123c', 'line-width': 2 }
          });
          map.addLayer({
            id: 'preview-point',
            type: 'circle',
            source: 'preview-features',
            paint: {
              'circle-color': '#f59e0b',
              'circle-radius': 5,
              'circle-stroke-color': '#111827',
              'circle-stroke-width': 1
            },
            filter: ['==', ['geometry-type'], 'Point']
          });
        }

        const bounds = bbox && bbox.length === 4 ? bbox : collection.bbox;
        if (bounds && bounds.every((value) => Number.isFinite(Number(value)))) {
          map.fitBounds([[Number(bounds[0]), Number(bounds[1])], [Number(bounds[2]), Number(bounds[3])]], {
            padding: 42,
            maxZoom: 12,
            duration: 400
          });
        }
      };

      if (map.loaded()) render();
      else map.once('load', render);
    }, [features, bbox]);
  }

  function Metric({ label, value }) {
    return e('div', { className: 'preview-metric' },
      e('span', null, label),
      e('strong', null, value || '-')
    );
  }

  function App() {
    const [summary, setSummary] = React.useState(null);
    const [featureCollection, setFeatureCollection] = React.useState(null);
    const [attributes, setAttributes] = React.useState({ columns: [], rows: [], pagination: null });
    const [page, setPage] = React.useState(1);
    const [loading, setLoading] = React.useState(true);
    const [tableLoading, setTableLoading] = React.useState(false);
    const [error, setError] = React.useState('');
    const [notice, setNotice] = React.useState('');

    usePreviewMap(featureCollection, summary && summary.bbox);

    React.useEffect(() => {
      setLoading(true);
      Promise.all([
        fetchJson(`/api/v1/jobs/${jobId}/preview/summary`),
        fetchJson(`/api/v1/jobs/${jobId}/preview/features?page=1&page_size=500`)
      ]).then(([summaryData, featureData]) => {
        setSummary(summaryData);
        setFeatureCollection(featureData);
        setError('');
      }).catch((err) => {
        setError(err.message);
      }).finally(() => setLoading(false));
    }, []);

    React.useEffect(() => {
      setTableLoading(true);
      fetchJson(`/api/v1/jobs/${jobId}/preview/attributes?page=${page}&page_size=${PAGE_SIZE}`)
        .then((data) => {
          setAttributes(data);
          setError('');
        })
        .catch((err) => setError(err.message))
        .finally(() => setTableLoading(false));
    }, [page]);

    function postAction(url, message) {
      setNotice('');
      fetchJson(url, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(() => setNotice(message))
        .catch((err) => setError(err.message));
    }

    const pagination = attributes.pagination || {};
    const start = pagination.total ? ((pagination.page - 1) * pagination.page_size) + 1 : 0;
    const end = pagination.total ? Math.min(pagination.page * pagination.page_size, pagination.total) : 0;

    return e('div', { className: 'preview-shell' },
      e('div', { className: 'preview-topbar' },
        e('div', { className: 'preview-title' },
          e('h1', null, 'Job Preview'),
          e('p', null, `Job ${jobId}`)
        ),
        e('div', { className: 'preview-actions' },
          e('a', { className: 'btn-secondary', href: jobsUrl, style: { margin: 0 } }, 'Back to Jobs'),
          e('a', { className: 'btn-secondary', href: outputUrl, style: { margin: 0 } }, 'Download Output'),
          e('button', {
            className: 'btn-secondary',
            style: { margin: 0 },
            onClick: () => postAction(`/api/v1/jobs/${jobId}/abort-after-preview`, 'Workflow aborted after preview.')
          }, 'Abort'),
          e('button', {
            className: 'btn-primary',
            style: { margin: 0, width: 'auto' },
            onClick: () => postAction(`/api/v1/jobs/${jobId}/confirm-preview`, 'Preview confirmed.')
          }, 'Confirm')
        )
      ),
      error ? e('div', { className: 'preview-error' }, error) : null,
      notice ? e('div', { className: 'preview-success' }, notice) : null,
      loading ? e('div', { className: 'preview-state preview-panel' }, 'Loading preview...') : null,
      summary ? e('div', { className: 'preview-metrics' },
        e(Metric, { label: 'Workflow', value: summary.workflow_code }),
        e(Metric, { label: 'Status', value: summary.status }),
        e(Metric, { label: 'Features', value: String(summary.feature_count) }),
        e(Metric, { label: 'Source', value: summary.source_file })
      ) : null,
      e('div', { className: 'preview-grid' },
        e('section', { className: 'preview-panel' },
          e('div', { className: 'preview-panel-header' },
            e('strong', null, 'Map'),
            e('span', { style: { color: 'var(--text-muted)', fontSize: '0.85rem' } }, summary && summary.bbox ? summary.bbox.map((v) => Number(v).toFixed(4)).join(', ') : 'No bounds')
          ),
          e('div', { id: 'job-preview-map' })
        ),
        e('section', { className: 'preview-panel' },
          e('div', { className: 'preview-panel-header' },
            e('strong', null, 'Attributes'),
            e('span', { style: { color: 'var(--text-muted)', fontSize: '0.85rem' } }, tableLoading ? 'Loading...' : `${start}-${end} of ${pagination.total || 0}`)
          ),
          e('div', { className: 'preview-table-wrap' },
            e('table', { className: 'preview-table' },
              e('thead', null,
                e('tr', null, attributes.columns.map((column) => e('th', { key: column }, column)))
              ),
              e('tbody', null,
                attributes.rows.length
                  ? attributes.rows.map((row, index) => e('tr', { key: index },
                      attributes.columns.map((column) => e('td', { key: column }, row[column] == null ? '' : String(row[column])))
                    ))
                  : e('tr', null, e('td', { colSpan: Math.max(attributes.columns.length, 1) }, 'No attributes available'))
              )
            )
          ),
          e('div', { className: 'preview-pager' },
            e('span', null, `${start}-${end} of ${pagination.total || 0}`),
            e('div', { className: 'preview-pager-buttons' },
              e('button', { className: 'btn-sm', disabled: !pagination.has_previous, onClick: () => setPage(page - 1) }, 'Previous'),
              e('button', { className: 'btn-sm', disabled: !pagination.has_next, onClick: () => setPage(page + 1) }, 'Next')
            )
          )
        )
      )
    );
  }

  ReactDOM.createRoot(root).render(e(App));
})();
