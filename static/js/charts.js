/**
 * Shared "distribution donut" chart used across the dashboards (creditors,
 * debtors, contributors, income, expense) so every pie/donut in the app
 * looks and behaves the same way: value + percentage always visible (not
 * only on hover), a legend with matching colors, and a running total in
 * the center of the donut.
 *
 * Requires Chart.js and chartjs-plugin-datalabels to already be loaded on
 * the page before this file.
 */
(function (global) {
  if (global.ChartDataLabels && global.Chart) {
    Chart.register(global.ChartDataLabels);
  }

  // Validated categorical palette (fixed order, not cycled) — see the
  // project's dataviz palette reference. This stays constant regardless of
  // the user's accent theme (categorical color identifies entities, it
  // isn't a branding surface) but a couple of neutrals are read live from
  // the page's design tokens so the chart still reads correctly in dark
  // mode.
  var CHART_PALETTE = [
    '#2a78d6', // blue
    '#eb6834', // orange
    '#1baf7a', // aqua
    '#eda100', // yellow
    '#e87ba4', // magenta
    '#008300', // green
  ];
  var MAX_SLICES = CHART_PALETTE.length; // beyond this, extra entries fold into "Other"

  function token(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return value ? value.trim() : fallback;
  }

  function formatAmount(value, currency) {
    var rounded = Math.round(value);
    return currency + rounded.toLocaleString('en-US');
  }

  function buildSlices(labels, data) {
    var entries = labels.map(function (label, i) {
      return { label: label, value: Number(data[i]) || 0 };
    });
    entries.sort(function (a, b) {
      return b.value - a.value;
    });

    if (entries.length <= MAX_SLICES) {
      return entries;
    }

    var top = entries.slice(0, MAX_SLICES - 1);
    var rest = entries.slice(MAX_SLICES - 1);
    var otherTotal = rest.reduce(function (sum, e) {
      return sum + e.value;
    }, 0);
    top.push({ label: 'Other (' + rest.length + ')', value: otherTotal, isOther: true });
    return top;
  }

  // Short form for tight spots (axis ticks, the donut centre): ৳1.2M, ৳850K.
  function compactAmount(value, currency) {
    var abs = Math.abs(value);
    var sign = value < 0 ? '-' : '';
    if (abs >= 1e6) return sign + currency + (abs / 1e6).toFixed(abs >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
    if (abs >= 1e3) return sign + currency + (abs / 1e3).toFixed(abs >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'K';
    return sign + currency + Math.round(abs);
  }

  // Centre total. Drawn as an HTML overlay rather than on the canvas so the
  // text can be measured and fitted properly, wrap its label, follow the
  // theme through CSS, and be read by screen readers.
  //
  // The overlay is the largest square that fits inside the hole
  // (side = innerRadius × √2), so nothing inside it can reach the ring.
  // The amount shrinks to fit; if it still can't at the smallest readable
  // size (CENTER_FULL_MIN_PX), it switches to the short form (৳10.6M) and
  // the exact figure moves into a tooltip.
  var CENTER_MIN_PX = 11;       // smallest size for anything in the centre
  var CENTER_FULL_MIN_PX = 14;  // below this the exact figure is too small to read, so go short
  var CENTER_MAX_PX = 26;

  function centerCompact(value, currency) {
    var abs = Math.abs(value), sign = value < 0 ? '-' : '';
    var units = [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
    for (var i = 0; i < units.length; i++) {
      if (abs >= units[i][0]) {
        var n = abs / units[i][0];
        return sign + currency + (n >= 100 ? Math.round(n) : n.toFixed(1).replace(/\.0$/, '')) + units[i][1];
      }
    }
    return sign + currency + Math.round(abs);
  }

  function mountCenter(canvas, label, full, compact) {
    var box = canvas.parentElement;
    if (getComputedStyle(box).position === 'static') box.style.position = 'relative';
    var old = box.querySelector('.donut-center');
    if (old) old.remove();
    var el = document.createElement('div');
    el.className = 'donut-center';
    el.innerHTML = '<span class="donut-center-label"></span><span class="donut-center-value"></span>';
    el.firstChild.textContent = label;
    el.lastChild.textContent = full;
    el.dataset.full = full;
    el.dataset.compact = compact;
    box.appendChild(el);
    return el;
  }

  function shrinkToFit(node, width, startPx, minPx) {
    var size = startPx;
    node.style.fontSize = size + 'px';
    while (node.scrollWidth > width && size > minPx) {
      size -= 1;
      node.style.fontSize = size + 'px';
    }
    return node.scrollWidth <= width ? size : 0;
  }

  function fitCenter(chart, el) {
    var arc = chart.getDatasetMeta(0).data[0];
    if (!arc || !arc.innerRadius) { el.style.visibility = 'hidden'; return; }
    var side = Math.floor(arc.innerRadius * Math.SQRT2);
    el.style.visibility = 'visible';
    el.style.left = arc.x + 'px';
    el.style.top = arc.y + 'px';
    el.style.width = el.style.height = side + 'px';

    var value = el.lastChild, label = el.firstChild;
    var start = Math.round(Math.max(CENTER_MIN_PX, Math.min(CENTER_MAX_PX, side / 4)));
    value.textContent = el.dataset.full;
    var size = shrinkToFit(value, side, start, Math.min(start, CENTER_FULL_MIN_PX));
    if (!size) {
      value.textContent = el.dataset.compact;
      size = shrinkToFit(value, side, start, CENTER_MIN_PX) || CENTER_MIN_PX;
      el.setAttribute('data-tip', el.dataset.full);
    } else {
      el.removeAttribute('data-tip');
    }
    label.style.fontSize = Math.max(9, Math.round(size * 0.46)) + 'px';
  }

  function centerPlugin(el) {
    var lastKey = '';
    return {
      id: 'donutCenter',
      // Checked on every draw (first render, window resize, and a chart that
      // started in a hidden tab getting its real size, which doesn't fire
      // afterUpdate), but only re-fitted when the hole actually moved or
      // changed size.
      afterDraw: function (chart) {
        var arc = chart.getDatasetMeta(0).data[0];
        var key = arc ? [Math.round(arc.x), Math.round(arc.y), Math.round(arc.innerRadius)].join() : '';
        if (key === lastKey) return;
        lastKey = key;
        fitCenter(chart, el);
      },
    };
  }

  /**
   * Render (or re-render) a distribution donut chart.
   * @param {Object} config
   * @param {string} config.canvasId
   * @param {string[]} config.labels
   * @param {number[]} config.data
   * @param {string} [config.currency='৳']
   * @param {string} [config.centerLabel='Total']
   */
  function renderDistributionChart(config) {
    var canvas = document.getElementById(config.canvasId);
    if (!canvas) return null;

    var labels = config.labels || [];
    var data = config.data || [];
    var currency = config.currency || '৳';
    var centerLabel = config.centerLabel || 'Total';

    var total = data.reduce(function (sum, v) {
      return sum + (Number(v) || 0);
    }, 0);

    if (labels.length === 0 || total <= 0) return null;

    var otherColor = token('--text-muted', '#9ca3af');
    var surfaceColor = token('--surface-raised', '#ffffff');
    var textColor = token('--text-secondary', '#374151');

    var slices = buildSlices(labels, data);
    var colors = slices.map(function (slice, i) {
      return slice.isOther ? otherColor : CHART_PALETTE[i % CHART_PALETTE.length];
    });

    var center = mountCenter(canvas, centerLabel, formatAmount(total, currency), centerCompact(total, currency));

    var chart = new Chart(canvas.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: slices.map(function (s) { return s.label; }),
        datasets: [
          {
            data: slices.map(function (s) { return s.value; }),
            backgroundColor: colors,
            borderWidth: 2,
            borderColor: surfaceColor,
            hoverOffset: 8,
          },
        ],
      },
      plugins: [centerPlugin(center)],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        layout: { padding: 8 },
        plugins: {
          legend: {
            display: config.showLegend !== false,
            position: 'bottom',
            labels: {
              usePointStyle: true,
              padding: window.innerWidth < 640 ? 10 : 14,
              boxWidth: 8,
              color: textColor,
              font: { size: 11, weight: '600' },
              generateLabels: function (chart) {
                var ds = chart.data.datasets[0];
                return chart.data.labels.map(function (label, i) {
                  var value = ds.data[i];
                  var pct = total > 0 ? ((value / total) * 100).toFixed(1) : '0.0';
                  return {
                    text: label + ' – ' + formatAmount(value, currency) + ' (' + pct + '%)',
                    fillStyle: ds.backgroundColor[i],
                    strokeStyle: ds.backgroundColor[i],
                    fontColor: textColor,
                    index: i,
                  };
                });
              },
            },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var value = ctx.raw;
                var pct = total > 0 ? ((value / total) * 100).toFixed(1) : '0.0';
                return ' ' + ctx.label + ': ' + formatAmount(value, currency) + ' (' + pct + '%)';
              },
            },
          },
          datalabels: {
            color: '#fff',
            textStrokeColor: 'rgba(0,0,0,0.35)',
            textStrokeWidth: 3,
            font: { weight: '700', size: 11 },
            formatter: function (value) {
              var pct = total > 0 ? (value / total) * 100 : 0;
              // Hide labels on slices too small to render text without
              // overlapping their neighbors; the legend/tooltip still
              // carry the exact figures for these.
              if (pct < 6) return '';
              return pct.toFixed(0) + '%';
            },
          },
        },
      },
    });

    // Web fonts change text widths; refit once they're in.
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { fitCenter(chart, center); });

    return chart;
  }

  /**
   * Render (or re-render) a monthly trend bar chart (e.g. rolling last 12
   * months). Supports one or more series (grouped bars) sharing the same
   * month labels — e.g. Borrowed vs Repaid, or a single Total Spent series.
   * @param {Object} config
   * @param {string} config.canvasId
   * @param {string[]} config.labels - month labels, e.g. "Aug 2025"
   * @param {Array<{label: string, data: number[]}>} config.datasets
   * @param {string} [config.currency='৳']
   */
  function renderTrendChart(config) {
    var canvas = document.getElementById(config.canvasId);
    if (!canvas) return null;

    var labels = config.labels || [];
    var datasets = config.datasets || [];
    var currency = config.currency || '৳';

    if (labels.length === 0 || datasets.length === 0) return null;

    var gridColor = token('--border-soft', '#e5e7eb');
    var textColor = token('--text-secondary', '#374151');

    var chartDatasets = datasets.map(function (ds, i) {
      return {
        label: ds.label,
        data: ds.data,
        backgroundColor: CHART_PALETTE[i % CHART_PALETTE.length],
        borderRadius: 4,
        maxBarThickness: 28,
      };
    });

    var chart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { labels: labels, datasets: chartDatasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: textColor, font: { size: 10 }, maxRotation: 0, autoSkip: true, autoSkipPadding: 8 },
          },
          y: {
            beginAtZero: true,
            grid: { color: gridColor },
            ticks: {
              color: textColor,
              font: { size: 10 },
              callback: function (value) { return compactAmount(value, currency); },
            },
          },
        },
        plugins: {
          legend: {
            display: datasets.length > 1,
            position: 'bottom',
            labels: { color: textColor, usePointStyle: true, font: { size: 11, weight: '600' } },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ' ' + ctx.dataset.label + ': ' + formatAmount(ctx.raw, currency);
              },
            },
          },
          datalabels: { display: false },
        },
      },
    });

    return chart;
  }

  // Theme/background switches apply without a reload, so re-read the
  // surface-dependent colours (donut slice gaps, grid lines) when they change.
  new MutationObserver(function () {
    if (!global.Chart) return;
    Object.values(global.Chart.instances).forEach(function (chart) {
      if (chart.config.type === 'doughnut') {
        chart.data.datasets[0].borderColor = token('--surface-raised', '#ffffff');
      } else if (chart.options.scales && chart.options.scales.y) {
        chart.options.scales.y.grid.color = token('--border-soft', '#e5e7eb');
      }
      chart.update('none');
    });
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-bg'] });

  global.renderDistributionChart = renderDistributionChart;
  global.renderTrendChart = renderTrendChart;
})(window);
