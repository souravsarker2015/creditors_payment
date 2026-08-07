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

  function centerTextPlugin(centerLabel, currency, total) {
    return {
      id: 'centerTotalText',
      afterDraw: function (chart) {
        var ctx = chart.ctx;
        var area = chart.chartArea;
        if (!area) return;
        var cx = (area.left + area.right) / 2;
        var cy = (area.top + area.bottom) / 2;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = "700 11px 'Inter', sans-serif";
        ctx.fillStyle = token('--text-muted', '#9ca3af');
        ctx.fillText(centerLabel.toUpperCase(), cx, cy - 12);
        ctx.font = "800 20px 'Inter', sans-serif";
        ctx.fillStyle = token('--text-primary', '#111827');
        ctx.fillText(formatAmount(total, currency), cx, cy + 12);
        ctx.restore();
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
      plugins: [centerTextPlugin(centerLabel, currency, total)],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        layout: { padding: 8 },
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              usePointStyle: true,
              padding: 14,
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
            ticks: { color: textColor, font: { size: 10 } },
          },
          y: {
            beginAtZero: true,
            grid: { color: gridColor },
            ticks: {
              color: textColor,
              font: { size: 10 },
              callback: function (value) { return formatAmount(value, currency); },
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

  global.renderDistributionChart = renderDistributionChart;
  global.renderTrendChart = renderTrendChart;
})(window);
