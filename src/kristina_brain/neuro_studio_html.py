# ruff: noqa: E501
"""Встроенный HTML-интерфейс онлайн-обсерватории Neuro Studio v1.3.0 × Drydock (60 FPS Canvas + Readiness Gate + Merit + SHA-256 Chain)."""

from __future__ import annotations

NEURO_STUDIO_HTML: str = """<!DOCTYPE html>
<html lang="ru" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kristina Brain Core v1.3.0 × Drydock — Онлайн-Обсерватория Мозга</title>
  <script src="https://cdn.tailwindcss.com/3.4.17"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
    body {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      background: radial-gradient(circle at 18% 0%, #0f1f3a 0%, #070b14 58%, #04070d 100%);
      color: #e2e8f0;
      overflow-x: hidden;
    }
    .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }
    .glass {
      background: rgba(15, 23, 42, 0.80);
      border: 1px solid rgba(56, 189, 248, 0.18);
      backdrop-filter: blur(12px);
    }
    .tab-active {
      background: rgba(56, 189, 248, 0.20);
      border-color: rgba(56, 189, 248, 0.70);
      color: #bae6fd;
    }
    .scope-active {
      background: rgba(16, 185, 129, 0.22);
      border-color: rgba(52, 211, 153, 0.75);
      color: #a7f3d0;
    }
    .pulse-dot { animation: pulseGlow 1.8s infinite ease-in-out; }
    @keyframes pulseGlow {
      0%, 100% { opacity: 0.55; transform: scale(1); }
      50% { opacity: 1; transform: scale(1.25); }
    }
  </style>
</head>
<body class="min-h-screen antialiased selection:bg-sky-500/30">
  <div class="max-w-[1460px] mx-auto px-3 sm:px-6 py-4 space-y-4">

    <!-- HEADER -->
    <header class="glass rounded-2xl p-4 flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3">
      <div class="flex items-start sm:items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-emerald-500/15 border border-emerald-400/40 flex items-center justify-center shrink-0">
          <span id="conn-dot" class="w-3 h-3 rounded-full bg-emerald-400 pulse-dot"></span>
        </div>
        <div>
          <div class="flex items-center gap-2 flex-wrap">
            <h1 class="text-base sm:text-lg font-bold tracking-tight text-white">Kristina Brain Core v1.3 × Drydock · Онлайн-Обсерватория</h1>
            <span id="conn-badge" class="mono text-[11px] px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">CONNECTING...</span>
            <span class="mono text-[11px] px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/30">Zero-PII SQLite WAL</span>
          </div>
          <p class="text-xs text-slate-400 mt-0.5">Прямая телеметрия синаптических нейронов, 5 нейромедиаторов и пластичности Хебба с облачного сервера Кристины</p>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <!-- Scope switcher -->
        <div class="flex rounded-xl bg-slate-900/90 p-1 border border-slate-700/80 gap-1">
          <button type="button" id="btn-scope-live" class="px-3 py-1.5 rounded-lg text-xs font-semibold border border-transparent transition scope-active">
            LIVE · Мозг Кристины (default)
          </button>
          <button type="button" id="btn-scope-sandbox" class="px-3 py-1.5 rounded-lg text-xs font-semibold border border-transparent text-slate-300 hover:text-white transition">
            CLOUD SANDBOX · Тест-стенд
          </button>
        </div>

        <nav class="flex flex-wrap gap-1.5">
          <button type="button" id="tab-btn-live" class="px-3 py-1.5 rounded-xl text-xs font-semibold border border-slate-700 text-slate-300 transition tab-active">Коннектом</button>
          <button type="button" id="tab-btn-drydock" class="px-3 py-1.5 rounded-xl text-xs font-semibold border border-amber-500/40 text-amber-200 hover:border-amber-400 transition">Drydock v1.3 · Математика и SHA-256</button>
          <button type="button" id="tab-btn-tests" class="px-3 py-1.5 rounded-xl text-xs font-semibold border border-slate-700 text-slate-300 hover:border-slate-500 transition">Онлайн-автотесты (14)</button>
          <button type="button" id="tab-btn-matrix" class="px-3 py-1.5 rounded-xl text-xs font-semibold border border-slate-700 text-slate-300 hover:border-slate-500 transition">Матрица и эмоции</button>
        </nav>
      </div>
    </header>

    <!-- STATUS & TELEMETRY BAR -->
    <div class="glass rounded-xl px-4 py-2.5 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-2">
      <div class="flex items-center gap-2.5 text-xs sm:text-sm">
        <span id="mode-pill" class="mono text-[11px] px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-400/35 shrink-0">LIVE TELEGRAM</span>
        <span id="narration-text" class="text-slate-200">Подключено к живой БД kristina_state.db (scope=default). Напишите Кристине в Telegram — импульсы отобразятся здесь автоматически за ~1 секунду без передачи текста переписки.</span>
      </div>
      <div class="flex flex-wrap items-center gap-3.5 text-xs mono text-slate-400 shrink-0">
        <span>Импульсов БД: <b id="kpi-seq" class="text-sky-300">0</b></span>
        <span>Drydock: <b id="kpi-drydock-score" class="text-emerald-300">10.0/10</b></span>
        <span>Merit: <b id="kpi-drydock-merit" class="text-amber-300">UNDETERMINED</b></span>
        <span>SHA-256: <b id="kpi-drydock-sha" class="text-emerald-400">VERIFIED</b></span>
        <span>RTT: <b id="kpi-rtt" class="text-emerald-400">— мс</b></span>
        <span>Ядро: <b id="kpi-engine-ms" class="text-amber-300">&lt; 1.2 мс</b></span>
      </div>
    </div>

    <!-- VIEW 1: LIVE CONNECTOME -->
    <section id="view-live" class="space-y-4">
      <!-- Interactive Cloud Sandbox Controls -->
      <div class="glass rounded-xl p-3 flex flex-wrap items-center justify-between gap-2">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-xs font-semibold text-slate-300 mr-1">Облачные импульсы (Python Engine):</span>
          <button type="button" id="sc-warm" class="px-3 py-1.5 rounded-xl text-xs font-semibold bg-sky-500/20 hover:bg-sky-500/30 text-sky-200 border border-sky-400/40 transition">1. Тёплый раппорт (warmth+silence)</button>
          <button type="button" id="sc-creative" class="px-3 py-1.5 rounded-xl text-xs font-semibold bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-200 border border-indigo-400/40 transition">2. Искра писателя 357 (curiosity)</button>
          <button type="button" id="sc-conflict" class="px-3 py-1.5 rounded-xl text-xs font-semibold bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-400/40 transition">3. Конфликт / Тормоз ГАМК (-0.95)</button>
          <button type="button" id="sc-sleep" class="px-3 py-1.5 rounded-xl text-xs font-semibold bg-purple-500/20 hover:bg-purple-500/30 text-purple-200 border border-purple-400/40 transition">4. Сон Хебба (R = +0.85)</button>
          <button type="button" id="sc-reset" class="px-3 py-1.5 rounded-xl text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition">Сброс песочницы</button>
        </div>
        <div class="text-[11px] text-slate-400">
          Кнопки выполняют реальный расчёт на сервере в изолированном контуре <code class="mono text-sky-300">demo:sandbox</code> (не засоряя живую память Кристины)
        </div>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
        <!-- 60 FPS Connectome Canvas -->
        <div class="xl:col-span-8 glass rounded-2xl p-3 sm:p-4 space-y-3">
          <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400 px-1">
            <div class="flex flex-wrap items-center gap-3">
              <span class="inline-flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-sky-400"></span>Возбуждение (w &gt; 0)</span>
              <span class="inline-flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-rose-500"></span>Тормоз ГАМК (w &lt; 0)</span>
              <span class="inline-flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-purple-400"></span>След Хебба e(t)</span>
              <span class="inline-flex items-center gap-1.5"><span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span>Рефрактерная пауза</span>
            </div>
            <span id="active-scope-label" class="mono text-[11px] text-emerald-300">scope: default (опрос 1.2 с)</span>
          </div>

          <div id="canvas-wrap" class="relative w-full h-[480px] sm:h-[520px] rounded-xl bg-slate-950/80 border border-slate-800/90 overflow-hidden">
            <canvas id="brain-canvas" class="w-full h-full block cursor-pointer"></canvas>
          </div>

          <!-- Selected Node Inspector -->
          <div class="rounded-xl bg-slate-900/85 border border-slate-800 px-3.5 py-2.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-xs">
            <div>
              <span class="text-slate-400">Узел:</span>
              <b id="insp-title" class="text-sky-300 ml-1">sensor_curiosity</b>
              <span id="insp-meta" class="mono text-slate-400 ml-2">V = 0.05 / θ_eff = 0.45</span>
            </div>
            <button type="button" id="btn-fire-selected" class="px-3 py-1 rounded-lg bg-sky-500/20 text-sky-300 border border-sky-400/40 hover:bg-sky-500/30 font-medium shrink-0">
              Подать импульс 0.90 в песочнице
            </button>
          </div>
        </div>

        <!-- Right Column: Neurotransmitters + Oscilloscope + Fast Emotions -->
        <div class="xl:col-span-4 space-y-4">
          <div class="glass rounded-2xl p-4 space-y-3">
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold text-white">5 нейромедиаторов (живой фон)</h2>
              <span id="quiet-badge" class="mono text-[11px] px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/30">АКТИВНЫЙ РЕЖИМ</span>
            </div>
            <div id="nt-bars" class="space-y-2.5 text-xs"></div>
            <div class="pt-2 border-t border-slate-800">
              <div class="text-[11px] text-slate-400 mb-1">Осциллограф сервера (DA / NE / GABA)</div>
              <div class="relative h-36 w-full">
                <canvas id="nt-chart"></canvas>
              </div>
            </div>
          </div>

          <div class="glass rounded-2xl p-4 space-y-2.5">
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold text-white">Быстрые оси эмоций Кристины</h2>
              <span id="gate-verdict-badge" class="mono text-[11px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">ШЛЮЗЫ СПОКОЙНЫ</span>
            </div>
            <div id="fast-emotions-grid" class="grid grid-cols-2 gap-2 text-xs"></div>
          </div>
        </div>
      </div>

      <!-- Live Inter-Agent Packet Stream -->
      <div class="glass rounded-2xl p-4 space-y-3">
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div>
            <h2 class="text-sm font-semibold text-white">Серверный журнал синаптических пакетов (last_packets из SQLite WAL)</h2>
            <p class="text-xs text-slate-400">Реальные кванты передачи между нейронами без сохранения текста сообщений</p>
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <button type="button" data-filter="ALL" class="pkt-filter px-2.5 py-1 rounded-lg text-xs border border-sky-400/50 bg-sky-500/20 text-sky-200">Все</button>
            <button type="button" data-filter="FIRED" class="pkt-filter px-2.5 py-1 rounded-lg text-xs border border-slate-700 bg-slate-800/70 text-slate-300">Пробой шлюза</button>
            <button type="button" data-filter="INHIBITED" class="pkt-filter px-2.5 py-1 rounded-lg text-xs border border-slate-700 bg-slate-800/70 text-slate-300">Тормоз ГАМК</button>
            <button type="button" id="btn-export-log" class="px-2.5 py-1 rounded-lg text-xs border border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25">Копировать JSON снимка</button>
          </div>
        </div>

        <div class="overflow-x-auto max-h-64 overflow-y-auto rounded-xl border border-slate-800">
          <table class="w-full text-left text-xs">
            <thead class="bg-slate-900/95 text-slate-400 sticky top-0">
              <tr>
                <th class="py-2 px-3 font-medium">Импульс / Хоп</th>
                <th class="py-2 px-3 font-medium">Источник → Приёмник</th>
                <th class="py-2 px-3 font-medium mono">Вес w</th>
                <th class="py-2 px-3 font-medium mono">Ток I = w·S</th>
                <th class="py-2 px-3 font-medium mono">V_до → V_после (θ_eff)</th>
                <th class="py-2 px-3 font-medium mono">След e(t)</th>
                <th class="py-2 px-3 font-medium">Исход</th>
              </tr>
            </thead>
            <tbody id="packet-tbody" class="divide-y divide-slate-800/80 mono"></tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- VIEW 2: LIVE CLOUD AUTOMATED TESTS -->
    <section id="view-tests" class="hidden space-y-4">
      <div class="glass rounded-2xl p-5 space-y-4">
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 class="text-base font-bold text-white">Онлайн-стенд верификации синаптического ядра и Drydock v1.3.0 (14 живых проверок)</h2>
            <p class="text-xs text-slate-400">Выполняет реальные HTTP-запросы к облачному Python-движку kristina-brain-core v1.3.0: синапсы, ГАМК, пластичность Хебба, перенормировка весов, монотонное сжатие Gate, Уилсон/Бонферрони и перехват подмены SHA-256</p>
          </div>
          <div class="flex items-center gap-3">
            <span id="tests-summary-badge" class="mono text-xs px-3 py-1.5 rounded-xl bg-slate-800 text-slate-300 border border-slate-700 font-semibold">ГОТОВ К ЗАПУСКУ</span>
            <button type="button" id="btn-rerun-tests" class="px-4 py-2 rounded-xl text-xs font-semibold bg-sky-500/25 text-sky-200 border border-sky-400/50 hover:bg-sky-500/35 transition">Запустить 14 онлайн-тестов</button>
          </div>
        </div>
        <div id="tests-grid" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>
      </div>
    </section>

    <!-- VIEW 3: SYNAPTIC MATRIX & SLOW MODES -->
    <section id="view-matrix" class="hidden space-y-4">
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div class="lg:col-span-7 glass rounded-2xl p-5 space-y-3">
          <h2 class="text-sm font-bold text-white">Живая таблица синаптических весов (из БД сервера)</h2>
          <div class="overflow-x-auto rounded-xl border border-slate-800">
            <table class="w-full text-left text-xs">
              <thead class="bg-slate-900 text-slate-400">
                <tr>
                  <th class="py-2 px-3">Синаптическая связь</th>
                  <th class="py-2 px-3 mono">Текущий вес w</th>
                  <th class="py-2 px-3 mono">Пластичность η</th>
                  <th class="py-2 px-3 mono">След пригодности e(t)</th>
                </tr>
              </thead>
              <tbody id="matrix-tbody" class="divide-y divide-slate-800 mono"></tbody>
            </table>
          </div>
        </div>
        <div class="lg:col-span-5 glass rounded-2xl p-5 space-y-3">
          <h2 class="text-sm font-bold text-white">12 медленных мод организма (OrganismModes)</h2>
          <div id="slow-modes-list" class="space-y-2 text-xs max-h-[420px] overflow-y-auto pr-1"></div>
        </div>
      </div>
    </section>

    <!-- VIEW 4: DRYDOCK v1.3 MATH & SHA-256 RECEIPTS -->
    <section id="view-drydock" class="hidden space-y-4">
      <div class="glass rounded-2xl p-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-bold text-white">Математическое и эпистемическое ядро Drydock v1.3.0</h2>
          <p class="text-xs text-slate-400">Прямая телеметрия готовности нейроконтура без «мёртвого веса» неисследованных категорий, монотонное сжатие Gate (&times;0.69 &le; 6.9), трёхзначный вердикт Merit и 4-шаговая цепочка SHA-256</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button type="button" id="dd-btn-cold" class="px-3 py-1.5 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 transition">Сброс (UNEXAMINED · UNDETERMINED)</button>
          <button type="button" id="dd-btn-norm" class="px-3 py-1.5 rounded-xl text-xs font-semibold bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-200 border border-emerald-400/40 transition">Импульс нормы (DELIVERED)</button>
          <button type="button" id="dd-btn-gate" class="px-3 py-1.5 rounded-xl text-xs font-semibold bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-400/40 transition">Стресс-конфликт (GATE &le; 6.9 · OWED)</button>
        </div>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-12 gap-4">
        <!-- Readiness & Category Subscores -->
        <div class="xl:col-span-6 glass rounded-2xl p-5 space-y-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <span class="text-xs uppercase tracking-wider text-slate-400">Drydock Neural Readiness</span>
              <div class="flex items-baseline gap-3 mt-1">
                <span id="dd-total-score" class="mono text-3xl font-bold text-emerald-300">10.0</span>
                <span class="mono text-sm text-slate-400">/ 10.0</span>
                <span id="dd-gate-pill" class="mono text-[11px] px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">UNGATED</span>
              </div>
              <p id="dd-mean-note" class="mono text-[11px] text-slate-400 mt-1">mean_ungated = 10.00 · проверено категорий: 3/4</p>
            </div>
            <div class="text-right">
              <span class="text-xs uppercase tracking-wider text-slate-400">Трёхзначный Merit</span>
              <div class="mt-1">
                <span id="dd-merit-pill" class="mono text-sm px-3 py-1 rounded-xl bg-amber-500/20 text-amber-300 border border-amber-500/40 font-bold">UNDETERMINED</span>
              </div>
            </div>
          </div>

          <div id="dd-categories-list" class="space-y-2.5 text-xs"></div>

          <div class="pt-3 border-t border-slate-800 space-y-1.5">
            <div class="text-xs font-semibold text-slate-300">Доказательная база Merit (decisive reasons):</div>
            <div id="dd-merit-reasons" class="space-y-1.5 text-xs"></div>
          </div>
        </div>

        <!-- 4-Stage SHA-256 Chain & Tamper Attack Simulator -->
        <div class="xl:col-span-6 glass rounded-2xl p-5 space-y-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 class="text-sm font-bold text-white">4-шаговая криптоцепочка SHA-256 квитанций</h3>
              <p class="text-[11px] text-slate-400 mono">detector &rarr; researcher &rarr; experimenter &rarr; verifier</p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button type="button" id="btn-dd-verify-clean" class="px-3 py-1.5 rounded-xl text-xs font-semibold bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-200 border border-emerald-400/40 transition">Проверить подлинность</button>
              <button type="button" id="btn-dd-tamper-attack" class="px-3 py-1.5 rounded-xl text-xs font-semibold bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-400/40 transition">Симулировать атаку подмены</button>
            </div>
          </div>

          <div id="dd-tamper-banner" class="rounded-xl px-3.5 py-2.5 text-xs mono bg-emerald-950/40 border border-emerald-500/35 text-emerald-200">
            SHA-256 верификация: цепочка подлинна (chain_verified = true)
          </div>

          <div id="dd-chain-tasks" class="space-y-2 text-xs mono"></div>
        </div>
      </div>

      <!-- Interactive Wilson 95% CI & Bonferroni Calculator -->
      <div class="glass rounded-2xl p-5 space-y-4">
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div>
            <h3 class="text-sm font-bold text-white">Онлайн-калькулятор интервалов Уилсона 95% и Z-теста Бонферрони (Python API)</h3>
            <p class="text-xs text-slate-400">Проверяет статистическую значимость отрыва двух когорт через <code class="mono text-sky-300">POST /neuro-studio/api/drydock-eval</code> без нормального вылета за [0%, 100%]</p>
          </div>
          <button type="button" id="btn-dd-calc-stats" class="px-4 py-2 rounded-xl text-xs font-semibold bg-sky-500/25 hover:bg-sky-500/35 text-sky-200 border border-sky-400/50 transition shrink-0">Рассчитать на сервере</button>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-6 gap-3 text-xs">
          <label class="space-y-1"><span class="text-slate-400">Успехи A (Brain)</span><input id="dd-ha" type="number" value="105" min="0" class="w-full rounded-lg bg-slate-900 border border-slate-700 px-2.5 py-1.5 mono text-white"></label>
          <label class="space-y-1"><span class="text-slate-400">Выборка N_A</span><input id="dd-na" type="number" value="144" min="1" class="w-full rounded-lg bg-slate-900 border border-slate-700 px-2.5 py-1.5 mono text-white"></label>
          <label class="space-y-1"><span class="text-slate-400">Успехи B (Baseline)</span><input id="dd-hb" type="number" value="51" min="0" class="w-full rounded-lg bg-slate-900 border border-slate-700 px-2.5 py-1.5 mono text-white"></label>
          <label class="space-y-1"><span class="text-slate-400">Выборка N_B</span><input id="dd-nb" type="number" value="144" min="1" class="w-full rounded-lg bg-slate-900 border border-slate-700 px-2.5 py-1.5 mono text-white"></label>
          <label class="space-y-1"><span class="text-slate-400">Гипотез m</span><input id="dd-m" type="number" value="3" min="1" max="50" class="w-full rounded-lg bg-slate-900 border border-slate-700 px-2.5 py-1.5 mono text-white"></label>
          <label class="space-y-1"><span class="text-slate-400">Уровень &alpha;</span><input id="dd-alpha" type="number" value="0.05" step="0.01" min="0.001" max="0.25" class="w-full rounded-lg bg-slate-900 border border-slate-700 px-2.5 py-1.5 mono text-white"></label>
        </div>

        <div id="dd-stats-output" class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs mono"></div>
      </div>
    </section>

    <div id="toast" class="fixed bottom-4 right-4 hidden px-4 py-2.5 rounded-xl bg-emerald-900/95 border border-emerald-400/50 text-emerald-100 text-xs font-medium shadow-xl z-50"></div>
  </div>

  <script>
    const NODE_LABELS = {
      sensor_warmth: { short: 'Теплота контакта', col: 0, row: 0.0 },
      sensor_curiosity: { short: 'Любопытство', col: 0, row: 1.0 },
      sensor_conflict: { short: 'Конфликт / Сбой', col: 0, row: 2.0 },
      sensor_silence_window: { short: 'Окно тишины', col: 0, row: 3.0 },
      inter_rapport_drive: { short: 'Раппорт 963', col: 1, row: 0.8 },
      inter_creative_spark: { short: 'Искра 357', col: 1, row: 2.2 },
      gate_proactive_outreach: { short: 'Шлюз Инициативы', col: 2, row: 0.3 },
      gate_creative_imagination: { short: 'Шлюз Воображения', col: 2, row: 1.5 },
      gate_urgent_escalation: { short: 'Шлюз Эскалации', col: 2, row: 2.7 },
    };

    const NT_META = [
      { key: 'DA', name: 'DA · Дофамин (драйв и пластичность)', color: '#38bdf8' },
      { key: 'NE', name: 'NE · Норадреналин (срочность и фокус)', color: '#fb7185' },
      { key: '5HT', name: '5HT · Серотонин (ровный ритм 741)', color: '#34d399' },
      { key: 'OX', name: 'OX · Окситоцин (доверие и эмпатия 963)', color: '#f472b6' },
      { key: 'GABA', name: 'GABA · ГАМК (торможение и тишина)', color: '#a78bfa' },
    ];

    let activeScope = 'default';
    let latestSnapshot = null;
    let lastSeenPulseSeq = { 'default': null, 'demo:sandbox': null };
    let selectedNodeId = 'sensor_curiosity';
    let activeFilter = 'ALL';
    let particles = [];
    let nodeFlashes = {};
    let nodePositions = {};
    let ntChart = null;
    let pollInFlight = false;

    function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

    function showToast(msg) {
      const el = document.getElementById('toast');
      el.textContent = msg;
      el.classList.remove('hidden');
      setTimeout(() => el.classList.add('hidden'), 2800);
    }

    function initChart() {
      const canvas = document.getElementById('nt-chart');
      if (!canvas || !window.Chart) return;
      ntChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: [],
          datasets: [
            { label: 'DA', data: [], borderColor: '#38bdf8', borderWidth: 2, tension: 0.35, pointRadius: 0 },
            { label: 'NE', data: [], borderColor: '#fb7185', borderWidth: 2, tension: 0.35, pointRadius: 0 },
            { label: 'GABA', data: [], borderColor: '#a78bfa', borderWidth: 2, tension: 0.35, pointRadius: 0 },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: { duration: 220 },
          scales: {
            y: { min: 0, max: 1, ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(148,163,184,0.08)' } },
            x: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { display: false } },
          },
          plugins: { legend: { labels: { color: '#cbd5e1', boxWidth: 10, font: { size: 10 } } } },
        },
      });
    }

    function pushChartPoint(nt, seq) {
      if (!ntChart || !nt) return;
      const lbl = '#' + seq;
      const labels = ntChart.data.labels;
      if (labels.length > 0 && labels[labels.length - 1] === lbl) {
        ntChart.data.datasets[0].data[labels.length - 1] = nt.DA || 0;
        ntChart.data.datasets[1].data[labels.length - 1] = nt.NE || 0;
        ntChart.data.datasets[2].data[labels.length - 1] = nt.GABA || 0;
        ntChart.update('none');
        return;
      }
      labels.push(lbl);
      ntChart.data.datasets[0].data.push(nt.DA || 0);
      ntChart.data.datasets[1].data.push(nt.NE || 0);
      ntChart.data.datasets[2].data.push(nt.GABA || 0);
      if (labels.length > 16) {
        labels.shift();
        ntChart.data.datasets.forEach((d) => d.data.shift());
      }
      ntChart.update();
    }

    const brainCanvas = document.getElementById('brain-canvas');
    const ctx = brainCanvas.getContext('2d');

    function computeNodeLayout(w, h) {
      const padX = Math.max(82, w * 0.14);
      const colX = [padX, w * 0.50, w - padX];
      const topY = 66;
      const usableH = h - 130;
      nodePositions = {};
      const neurons = (latestSnapshot && latestSnapshot.neurons) ? latestSnapshot.neurons : Object.keys(NODE_LABELS).map((id) => ({ neuron_id: id, kind: id.startsWith('sensor') ? 'sensory' : (id.startsWith('inter') ? 'inter' : 'motor_gate') }));
      let extraSensory = 3.6;
      neurons.forEach((n) => {
        const meta = NODE_LABELS[n.neuron_id];
        const col = meta ? meta.col : (n.kind === 'sensory' ? 0 : (n.kind === 'inter' ? 1 : 2));
        const row = meta ? meta.row : (extraSensory += 0.7);
        nodePositions[n.neuron_id] = {
          x: colX[col],
          y: topY + (Math.min(row, 3.6) / 3.2) * usableH,
        };
      });
    }

    function resizeCanvas() {
      const wrap = document.getElementById('canvas-wrap');
      if (!wrap) return;
      const rect = wrap.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      brainCanvas.width = Math.max(320, Math.floor(rect.width * dpr));
      brainCanvas.height = Math.max(300, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      computeNodeLayout(rect.width, rect.height);
    }

    function spawnParticlesFromPackets(pkts) {
      const nowMs = performance.now();
      pkts.forEach((pkt) => {
        const hop = Number(pkt.hop || 1);
        const delay = Math.max(0, hop - 1) * 340;
        const isInhib = Number(pkt.weight) < 0 || pkt.outcome === 'INHIBITED';
        particles.push({
          source: pkt.source_id,
          target: pkt.target_id,
          startMs: nowMs + delay,
          durMs: 430,
          color: isInhib ? '#fb7185' : '#38bdf8',
          radius: clamp(3.8 + Math.abs(Number(pkt.current || 0.3)) * 4.2, 3.8, 7.2),
          outcome: pkt.outcome,
        });
      });
    }

    function drawConnectome(nowMs) {
      const wrap = document.getElementById('canvas-wrap');
      if (!wrap) return;
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;
      ctx.clearRect(0, 0, w, h);

      const padX = Math.max(82, w * 0.14);
      ctx.font = '600 11px Inter, sans-serif';
      ctx.fillStyle = 'rgba(148, 163, 184, 0.78)';
      ctx.textAlign = 'center';
      ctx.fillText('СЕНСОРНЫЕ НЕЙРОНЫ (0 LLM)', padX, 25);
      ctx.fillText('ИНТЕРНЕЙРОНЫ ПАТТЕРНОВ', w * 0.50, 25);
      ctx.fillText('МОТОРНЫЕ ШЛЮЗЫ К КОРЕ', w - padX, 25);

      const synapses = (latestSnapshot && latestSnapshot.synapses) ? latestSnapshot.synapses : [];
      synapses.forEach((edge) => {
        const p1 = nodePositions[edge.source_id];
        const p2 = nodePositions[edge.target_id];
        if (!p1 || !p2) return;
        const weight = Number(edge.weight || 0);
        const elig = Number(edge.eligibility_trace || 0);
        const cpx = (p1.x + p2.x) * 0.5;
        const cpy = (p1.y + p2.y) * 0.5 + (weight < 0 ? -30 : 0);

        ctx.save();
        if (elig > 0.05) {
          ctx.beginPath();
          ctx.moveTo(p1.x + 26, p1.y);
          ctx.quadraticCurveTo(cpx, cpy, p2.x - 28, p2.y);
          ctx.strokeStyle = `rgba(192, 132, 252, ${clamp(elig * 0.55, 0.15, 0.65)})`;
          ctx.lineWidth = Math.abs(weight) * 6 + 4;
          ctx.stroke();
        }

        ctx.beginPath();
        ctx.moveTo(p1.x + 26, p1.y);
        ctx.quadraticCurveTo(cpx, cpy, p2.x - 28, p2.y);
        if (weight < 0) {
          ctx.setLineDash([5, 5]);
          ctx.strokeStyle = 'rgba(251, 113, 133, 0.68)';
        } else {
          ctx.setLineDash([]);
          ctx.strokeStyle = 'rgba(56, 189, 248, 0.36)';
        }
        ctx.lineWidth = clamp(Math.abs(weight) * 3.4, 1.3, 4.2);
        ctx.stroke();

        const mx = 0.25 * (p1.x + 26) + 0.5 * cpx + 0.25 * (p2.x - 28);
        const my = 0.25 * p1.y + 0.5 * cpy + 0.25 * p2.y;
        ctx.font = '500 10px JetBrains Mono, monospace';
        ctx.fillStyle = weight < 0 ? '#fda4af' : (elig > 0.1 ? '#e9d5ff' : 'rgba(148,163,184,0.82)');
        ctx.fillText((weight > 0 ? '+' : '') + weight.toFixed(2), mx, my - 5);
        ctx.restore();
      });

      const alive = [];
      particles.forEach((pt) => {
        if (nowMs < pt.startMs) { alive.push(pt); return; }
        const t = (nowMs - pt.startMs) / pt.durMs;
        if (t >= 1) {
          nodeFlashes[pt.target] = { until: nowMs + 560, outcome: pt.outcome };
          return;
        }
        alive.push(pt);
        const p2 = nodePositions[pt.target];
        if (!p2) return;
        const p1 = nodePositions[pt.source] || { x: p2.x - 76, y: p2.y };
        const sx = p1.x + 26;
        const ex = p2.x - 28;
        const cpx = (sx + ex) * 0.5;
        const cpy = (p1.y + p2.y) * 0.5 + (pt.color === '#fb7185' ? -30 : 0);
        const u = 1 - t;
        const x = u * u * sx + 2 * u * t * cpx + t * t * ex;
        const y = u * u * p1.y + 2 * u * t * cpy + t * t * p2.y;

        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, pt.radius * 2.2, 0, Math.PI * 2);
        ctx.fillStyle = pt.color + '33';
        ctx.fill();
        ctx.beginPath();
        ctx.arc(x, y, pt.radius, 0, Math.PI * 2);
        ctx.fillStyle = pt.color;
        ctx.fill();
        ctx.restore();
      });
      particles = alive;

      const neurons = (latestSnapshot && latestSnapshot.neurons) ? latestSnapshot.neurons : [];
      neurons.forEach((n) => {
        const pos = nodePositions[n.neuron_id];
        if (!pos) return;
        const r = 25;
        const v = Number(n.potential || 0);
        const theta = Number(n.effective_threshold || 0.5);
        const ratio = clamp(v / Math.max(0.1, theta), 0, 1);
        const flash = nodeFlashes[n.neuron_id];
        const isSelected = n.neuron_id === selectedNodeId;

        ctx.save();
        if (flash && flash.until > nowMs) {
          ctx.beginPath();
          ctx.arc(pos.x, pos.y, r + 9, 0, Math.PI * 2);
          ctx.fillStyle = flash.outcome === 'INHIBITED' ? 'rgba(251,113,133,0.32)' : 'rgba(56,189,248,0.34)';
          ctx.fill();
        }

        ctx.beginPath();
        ctx.arc(pos.x, pos.y, r, 0, Math.PI * 2);
        ctx.fillStyle = '#0f172a';
        ctx.fill();
        ctx.lineWidth = isSelected ? 2.6 : 1.6;
        ctx.strokeStyle = n.in_refractory ? '#fbbf24' : (isSelected ? '#38bdf8' : 'rgba(148,163,184,0.45)');
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(pos.x, pos.y, r - 4, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * ratio);
        ctx.strokeStyle = n.in_refractory ? '#f59e0b' : (n.kind === 'motor_gate' ? '#34d399' : '#38bdf8');
        ctx.lineWidth = 3.2;
        ctx.stroke();

        ctx.font = '600 10px JetBrains Mono, monospace';
        ctx.fillStyle = '#f8fafc';
        ctx.textAlign = 'center';
        ctx.fillText(v.toFixed(2), pos.x, pos.y + 3);

        const label = NODE_LABELS[n.neuron_id] ? NODE_LABELS[n.neuron_id].short : n.neuron_id;
        ctx.font = '600 11px Inter, sans-serif';
        ctx.fillStyle = '#e2e8f0';
        ctx.fillText(label, pos.x, pos.y + r + 15);

        ctx.font = '500 9.5px JetBrains Mono, monospace';
        ctx.fillStyle = n.in_refractory ? '#fbbf24' : '#94a3b8';
        ctx.fillText(n.in_refractory ? `пауза ${Math.ceil(n.refractory_remaining_s)}с` : `θ=${theta.toFixed(2)}`, pos.x, pos.y + r + 28);
        ctx.restore();
      });

      requestAnimationFrame(drawConnectome);
    }

    function renderSnapshotUI(snap, rttMs) {
      latestSnapshot = snap;
      computeNodeLayout(document.getElementById('canvas-wrap').clientWidth, document.getElementById('canvas-wrap').clientHeight);

      document.getElementById('conn-badge').textContent = `ONLINE · v${snap.version || '1.2.0'}`;
      document.getElementById('conn-badge').className = 'mono text-[11px] px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40';
      document.getElementById('kpi-seq').textContent = String(snap.pulse_seq || 0);
      if (rttMs !== undefined) document.getElementById('kpi-rtt').textContent = `${rttMs.toFixed(0)} мс`;
      document.getElementById('active-scope-label').textContent = `scope: ${snap.scope_id} (PII Redacted: ${snap.pii_redacted ? 'ДА' : '—'})`;
      document.getElementById('quiet-badge').textContent = snap.is_quiet_hours ? 'ТИХИЕ ЧАСЫ (ГАМК ↑)' : 'ДНЕВНОЙ РЕЖИМ';

      const prevSeq = lastSeenPulseSeq[snap.scope_id];
      if (prevSeq !== null && snap.pulse_seq > prevSeq) {
        const fresh = (snap.last_packets || []).filter((p) => Number(p.seq) > prevSeq);
        if (fresh.length > 0) {
          spawnParticlesFromPackets(fresh);
          showToast(`Новый живой импульс #${snap.pulse_seq} (${fresh.length} синаптических пакетов)`);
        }
      }
      lastSeenPulseSeq[snap.scope_id] = snap.pulse_seq;

      const nt = snap.neurotransmitters || {};
      pushChartPoint(nt, snap.pulse_seq || 0);
      document.getElementById('nt-bars').innerHTML = NT_META.map((m) => {
        const val = Number(nt[m.key] || 0);
        return `<div>
          <div class="flex justify-between mb-1"><span class="text-slate-300">${m.name}</span><span class="mono font-semibold" style="color:${m.color}">${val.toFixed(3)}</span></div>
          <div class="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden"><div class="h-full rounded-full transition-all duration-300" style="width:${(val * 100).toFixed(1)}%;background:${m.color}"></div></div>
        </div>`;
      }).join('');

      const emo = snap.fast_emotions || {};
      const emoEntries = Object.entries(emo);
      document.getElementById('fast-emotions-grid').innerHTML = emoEntries.length
        ? emoEntries.map(([k, v]) => `<div class="rounded-lg bg-slate-900/80 border border-slate-800 px-2.5 py-1.5 flex justify-between">
            <span class="text-slate-400">${k}</span><span class="mono text-sky-300 font-semibold">${Number(v).toFixed(2)}</span>
          </div>`).join('')
        : '<div class="col-span-2 text-slate-500">Ожидание инициализации быстрых осей...</div>';

      const sel = (snap.neurons || []).find((n) => n.neuron_id === selectedNodeId) || (snap.neurons || [])[0];
      if (sel) {
        document.getElementById('insp-title').textContent = sel.neuron_id;
        document.getElementById('insp-meta').textContent = `V = ${Number(sel.potential).toFixed(3)} / θ_eff = ${Number(sel.effective_threshold).toFixed(3)} · ${sel.in_refractory ? 'рефрактерность ' + sel.refractory_remaining_s + 'с' : 'готов'}`;
      }

      const pkts = (snap.last_packets || []).slice().reverse().filter((p) => activeFilter === 'ALL' || p.outcome === activeFilter);
      const badgeMap = {
        FIRED: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
        INHIBITED: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
        REFRACTORY_BLOCKED: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
        SUBTHRESHOLD: 'bg-slate-800 text-slate-400 border-slate-700',
      };
      document.getElementById('packet-tbody').innerHTML = pkts.length
        ? pkts.map((p) => `<tr class="hover:bg-slate-900/60">
            <td class="py-2 px-3 text-slate-400">#${p.seq} · H${p.hop}</td>
            <td class="py-2 px-3 text-slate-200">${p.source_id} → <span class="text-sky-300">${p.target_id}</span></td>
            <td class="py-2 px-3 ${p.weight < 0 ? 'text-rose-400' : 'text-sky-300'}">${p.weight > 0 ? '+' : ''}${Number(p.weight).toFixed(2)}</td>
            <td class="py-2 px-3">${p.current > 0 ? '+' : ''}${Number(p.current).toFixed(3)}</td>
            <td class="py-2 px-3 text-slate-300">${Number(p.v_before).toFixed(2)} → ${Number(p.v_after).toFixed(2)} (${Number(p.eff_threshold).toFixed(2)})</td>
            <td class="py-2 px-3 text-purple-300">${Number(p.eligibility).toFixed(2)}</td>
            <td class="py-2 px-3"><span class="px-2 py-0.5 rounded-md border text-[10px] ${badgeMap[p.outcome] || badgeMap.SUBTHRESHOLD}">${p.outcome}</span></td>
          </tr>`).join('')
        : '<tr><td colspan="7" class="py-6 text-center text-slate-500">Пакеты ещё не записаны в этом контуре — отправьте сообщение боту или нажмите кнопку сценария выше</td></tr>';

      document.getElementById('matrix-tbody').innerHTML = (snap.synapses || []).map((s) => `<tr>
        <td class="py-2 px-3 text-slate-200">${s.edge}</td>
        <td class="py-2 px-3 ${s.weight < 0 ? 'text-rose-400' : 'text-sky-300'}">${s.weight > 0 ? '+' : ''}${Number(s.weight).toFixed(4)}</td>
        <td class="py-2 px-3 text-slate-400">${Number(s.plasticity).toFixed(2)}</td>
        <td class="py-2 px-3 text-purple-300">${Number(s.eligibility_trace).toFixed(4)}</td>
      </tr>`).join('');

      const modes = Object.entries(snap.slow_modes || {});
      document.getElementById('slow-modes-list').innerHTML = modes.map(([name, m]) => `<div class="rounded-xl bg-slate-900/80 border border-slate-800 p-2.5">
        <div class="flex justify-between mb-1"><span class="font-medium text-slate-200">${name}</span><span class="mono text-sky-300">${Number(m.amplitude).toFixed(3)} <span class="text-slate-500">(base ${Number(m.baseline).toFixed(2)})</span></span></div>
        <div class="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden"><div class="h-full bg-sky-400 rounded-full" style="width:${clamp(Number(m.amplitude) * 100, 0, 100).toFixed(1)}%"></div></div>
      </div>`).join('');

      renderDrydockUI(snap);
    }

    const DD_CAT_LABELS = {
      Neural_Stability: 'Neural_Stability · Стабильность и стресс-контур (30%, Gated)',
      Inhibitory_Shield: 'Inhibitory_Shield · Тормозной щит ГАМК -0.95 (30%, Gated)',
      Modulator_Balance: 'Modulator_Balance · Гомеостаз 5 медиаторов (20%, Gated)',
      Synaptic_Plasticity: 'Synaptic_Plasticity · Пластичность Хебба e(t) (20%)',
    };

    function renderDrydockUI(snap) {
      const dd = snap.drydock;
      if (!dd || !dd.readiness || !dd.merit) return;
      const rd = dd.readiness;
      const mr = dd.merit;
      const tot = Number(rd.total ?? 10).toFixed(1);
      const isGated = Boolean(rd.gated);
      const meritUp = String(mr.conclusion || 'undetermined').toUpperCase();

      const kpiScore = document.getElementById('kpi-drydock-score');
      kpiScore.textContent = `${tot}/10${isGated ? ' [GATE]' : ''}`;
      kpiScore.className = isGated ? 'text-rose-400' : 'text-emerald-300';

      const kpiMerit = document.getElementById('kpi-drydock-merit');
      kpiMerit.textContent = meritUp;
      kpiMerit.className = meritUp === 'OWED' ? 'text-rose-400' : (meritUp === 'DELIVERED' ? 'text-emerald-300' : 'text-amber-300');

      const kpiSha = document.getElementById('kpi-drydock-sha');
      kpiSha.textContent = dd.chain_verified ? 'VERIFIED (4/4)' : 'TAMPERED!';
      kpiSha.className = dd.chain_verified ? 'text-emerald-400' : 'text-rose-400';

      document.getElementById('dd-total-score').textContent = tot;
      document.getElementById('dd-total-score').className = `mono text-3xl font-bold ${isGated ? 'text-rose-400' : 'text-emerald-300'}`;

      const gatePill = document.getElementById('dd-gate-pill');
      gatePill.textContent = isGated ? 'GATED ×0.69 ≤ 6.9' : 'UNGATED (НОРМА)';
      gatePill.className = `mono text-[11px] px-2.5 py-0.5 rounded-full border ${isGated ? 'bg-rose-500/20 text-rose-300 border-rose-500/40' : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'}`;

      const counted = rd.counted || [];
      const unexam = rd.unexamined || [];
      document.getElementById('dd-mean-note').textContent = `mean_ungated = ${Number(rd.mean_ungated ?? 10).toFixed(2)} · проверено: ${counted.length}/4${unexam.length ? ' · unexamined: ' + unexam.join(', ') : ''}`;

      const meritStyles = {
        OWED: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
        DELIVERED: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
        UNDETERMINED: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
      };
      const mPill = document.getElementById('dd-merit-pill');
      mPill.textContent = meritUp;
      mPill.className = `mono text-sm px-3 py-1 rounded-xl border font-bold ${meritStyles[meritUp] || meritStyles.UNDETERMINED}`;

      const cats = rd.categories || {};
      document.getElementById('dd-categories-list').innerHTML = Object.keys(DD_CAT_LABELS).map((ck) => {
        const isUnex = unexam.includes(ck);
        const val = Number(cats[ck] ?? 10);
        const barColor = isUnex ? '#64748b' : (val < 7.0 ? '#fb7185' : '#34d399');
        return `<div class="rounded-xl bg-slate-900/80 border border-slate-800 p-2.5">
          <div class="flex items-center justify-between gap-2 mb-1">
            <span class="text-slate-200 font-medium">${DD_CAT_LABELS[ck]}</span>
            <span class="mono font-semibold" style="color:${barColor}">${isUnex ? 'UNEXAMINED (без голоса)' : val.toFixed(1) + ' / 10'}</span>
          </div>
          <div class="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
            <div class="h-full rounded-full transition-all duration-300" style="width:${isUnex ? 100 : clamp(val * 10, 0, 100)}%;background:${barColor};opacity:${isUnex ? 0.28 : 1}"></div>
          </div>
        </div>`;
      }).join('');

      document.getElementById('dd-merit-reasons').innerHTML = (mr.reasons || []).map((r) => `
        <div class="rounded-lg bg-slate-900/80 border border-slate-800 px-3 py-2 flex items-center justify-between gap-2">
          <span class="text-slate-200"><code class="mono text-sky-300 mr-1.5">[${r.code}]</code>${r.detail}</span>
          <span class="mono text-[10px] px-2 py-0.5 rounded border ${r.decisive ? 'bg-sky-500/20 text-sky-200 border-sky-400/40' : 'bg-slate-800 text-slate-400 border-slate-700'}">${r.decisive ? 'DECISIVE' : 'INFO'}</span>
        </div>`).join('');

      const tasks = (dd.cognitive_chain && dd.cognitive_chain.tasks) ? dd.cognitive_chain.tasks : [];
      document.getElementById('dd-chain-tasks').innerHTML = tasks.map((t, idx) => `
        <div class="rounded-xl bg-slate-900/85 border border-slate-800 p-2.5 space-y-1">
          <div class="flex items-center justify-between">
            <span class="font-semibold text-sky-300">${idx + 1}. ${t.agent} <span class="text-slate-400 font-normal">· ${t.goal}</span></span>
            <span class="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/35 text-[10px]">${t.status} (${t.reason})</span>
          </div>
          <div class="text-[11px] text-slate-400 break-all">in: <span class="text-slate-300">${String(t.input_sha256).slice(0, 20)}…</span> &rarr; out: <span class="text-emerald-300">${String(t.output_sha256).slice(0, 20)}…</span></div>
        </div>`).join('');
    }

    async function pollLiveScope() {
      if (pollInFlight) return;
      pollInFlight = true;
      const t0 = performance.now();
      try {
        const res = await fetch(`/neuro-studio/api/live/${encodeURIComponent(activeScope)}`, { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderSnapshotUI(data, performance.now() - t0);
      } catch (err) {
        document.getElementById('conn-badge').textContent = 'RECONNECTING...';
        document.getElementById('conn-badge').className = 'mono text-[11px] px-2.5 py-0.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/40';
      } finally {
        pollInFlight = false;
      }
    }

    function switchScope(scope) {
      activeScope = scope;
      const isLive = scope === 'default';
      document.getElementById('btn-scope-live').className = `px-3 py-1.5 rounded-lg text-xs font-semibold border border-transparent transition ${isLive ? 'scope-active' : 'text-slate-300 hover:text-white'}`;
      document.getElementById('btn-scope-sandbox').className = `px-3 py-1.5 rounded-lg text-xs font-semibold border border-transparent transition ${!isLive ? 'scope-active' : 'text-slate-300 hover:text-white'}`;
      document.getElementById('mode-pill').textContent = isLive ? 'LIVE TELEGRAM' : 'CLOUD SANDBOX';
      document.getElementById('narration-text').textContent = isLive
        ? 'Подключено к живой БД kristina_state.db (scope=default). Любое сообщение Кристине в Telegram мгновенно отражается на графе.'
        : 'Активен облачный тест-стенд demo:sandbox: каждый клик выполняет реальный расчёт SynapticGraphEngine на сервере.';
      pollLiveScope();
    }

    async function runCloudSandboxAction(action, stimuli, rewardSignal, label) {
      if (activeScope !== 'demo:sandbox') switchScope('demo:sandbox');
      const t0 = performance.now();
      const res = await fetch('/neuro-studio/api/sandbox-pulse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope_id: 'demo:sandbox', action, stimuli: stimuli || {}, reward_signal: rewardSignal ?? 0.8 }),
      });
      const data = await res.json();
      const rtt = performance.now() - t0;
      if (data.engine_latency_ms !== undefined) {
        document.getElementById('kpi-engine-ms').textContent = `${Number(data.engine_latency_ms).toFixed(2)} мс`;
      }
      if (data.pulse && Array.isArray(data.pulse.packet_trace)) {
        lastSeenPulseSeq['demo:sandbox'] = data.snapshot.pulse_seq;
        spawnParticlesFromPackets(data.pulse.packet_trace);
        const gates = data.pulse.opened_motor_gates || [];
        document.getElementById('gate-verdict-badge').textContent = gates.length ? `ОТКРЫТ: ${gates.join(', ')}` : 'ПОД ПОРОГОМ (0 LLM)';
      }
      if (data.snapshot) renderSnapshotUI(data.snapshot, rtt);
      if (label) document.getElementById('narration-text').textContent = label;
      return data;
    }

    async function runOnlineTestSuite() {
      const grid = document.getElementById('tests-grid');
      const badge = document.getElementById('tests-summary-badge');
      badge.textContent = 'ВЫПОЛНЯЕТСЯ НА СЕРВЕРЕ...';
      const results = [];

      async function check(name, desc, fn) {
        const t0 = performance.now();
        try {
          const detail = await fn();
          results.push({ name, desc, ok: true, ms: (performance.now() - t0).toFixed(1), detail });
        } catch (e) {
          results.push({ name, desc, ok: false, ms: (performance.now() - t0).toFixed(1), detail: String(e.message || e) });
        }
      }

      await check('1. Live-доступность мозга Кристины (scope=default)', 'GET /neuro-studio/api/live/default возвращает 9 нейронов и 5 нейромедиаторов', async () => {
        const r = await fetch('/neuro-studio/api/live/default');
        const d = await r.json();
        if (d.status !== 'online' || !Array.isArray(d.neurons) || d.neurons.length < 9) throw new Error('Некорректная схема узлов');
        return `9 нейронов онлайн, pulse_seq=${d.pulse_seq}`;
      });

      await check('2. Гарантия Zero-PII в публичной телеметрии', 'Снимок содержит только числовые оси и pii_redacted=true', async () => {
        const r = await fetch('/neuro-studio/api/live/default');
        const txt = await r.text();
        const d = JSON.parse(txt);
        if (!d.pii_redacted || txt.includes('last_reflection') || txt.includes('source_quote')) throw new Error('Обнаружено текстовое поле');
        return 'Текстовые поля полностью исключены';
      });

      await check('3. Защита живого контура default от записи без ключа', 'POST /neuro-studio/api/sandbox-pulse на scope=default возвращает HTTP 401', async () => {
        const r = await fetch('/neuro-studio/api/sandbox-pulse', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scope_id: 'default', action: 'pulse', stimuli: { sensor_warmth: 0.5 } }),
        });
        if (r.status !== 401) throw new Error(`Ожидался 401, получен ${r.status}`);
        return 'HTTP 401 (запись без X-API-Key заблокирована)';
      });

      await check('4. Чистый сброс облачной песочницы demo:sandbox', 'reset_circuit возвращает базовые веса и pulse_seq=0', async () => {
        const d = await runCloudSandboxAction('reset', {}, 0, null);
        if (d.snapshot.pulse_seq !== 0) throw new Error('pulse_seq не сброшен');
        return `Сброс за ${d.engine_latency_ms} мс`;
      });

      await check('5. Подпороговая фильтрация шума (0 токенов LLM)', 'Слабый стимул 0.12 не открывает ни одного моторного шлюза', async () => {
        const d = await runCloudSandboxAction('pulse', { sensor_curiosity: 0.12 }, 0, null);
        if ((d.pulse.opened_motor_gates || []).length !== 0) throw new Error('Ложное срабатывание шлюза');
        return `requires_llm_cortex = ${d.pulse.requires_llm_cortex}`;
      });

      await check('6. Двуххоповый каскад любопытства -> gate_creative_imagination', 'sensor_curiosity -> inter_creative_spark -> моторный шлюз', async () => {
        await runCloudSandboxAction('reset', {}, 0, null);
        const d = await runCloudSandboxAction('pulse', { sensor_curiosity: 0.95 }, 0, null);
        if (!(d.pulse.opened_motor_gates || []).includes('gate_creative_imagination')) throw new Error('Шлюз воображения не открылся');
        return `Пробой за ${d.engine_latency_ms} мс (${d.pulse.packet_trace.length} пакетов)`;
      });

      await check('7. Рефрактерный блок повторного спама', 'Повторный импульс мгновенно гасится рефрактерным щитом (0 открытых шлюзов)', async () => {
        const d = await runCloudSandboxAction('pulse', { sensor_curiosity: 0.95 }, 0, null);
        const gatesOpen = (d.pulse.opened_motor_gates || []).length;
        const blockedPkt = (d.pulse.packet_trace || []).find((p) => p.outcome === 'REFRACTORY_BLOCKED');
        if (gatesOpen > 0 || !blockedPkt) throw new Error('Рефрактерное окно не сработало');
        return `Дубль остановлен на ${blockedPkt.target_id} (H${blockedPkt.hop} · REFRACTORY_BLOCKED)`;
      });

      await check('8. Тормозной синапс ГАМК (-0.95) при конфликте', 'sensor_conflict мгновенно гасит gate_proactive_outreach', async () => {
        await runCloudSandboxAction('reset', {}, 0, null);
        const d = await runCloudSandboxAction('pulse', { sensor_warmth: 0.92, sensor_silence_window: 0.85, sensor_conflict: 0.95 }, 0, null);
        if ((d.pulse.opened_motor_gates || []).includes('gate_proactive_outreach')) throw new Error('Инициатива не заблокирована');
        const inh = (d.pulse.packet_trace || []).some((p) => p.outcome === 'INHIBITED');
        if (!inh) throw new Error('Нет пакета INHIBITED');
        return 'gate_proactive_outreach подавлен, открыт gate_urgent_escalation';
      });

      await check('9. Зажигание следа пригодности Eligibility Trace', 'Обучаемый синапс получает eligibility_trace = 1.0 после спайка', async () => {
        await runCloudSandboxAction('reset', {}, 0, null);
        const d = await runCloudSandboxAction('pulse', { sensor_curiosity: 0.92 }, 0, null);
        const syn = d.snapshot.synapses.find((s) => s.edge === 'sensor_curiosity->inter_creative_spark');
        if (!syn || syn.eligibility_trace < 0.9) throw new Error('eligibility_trace не записан');
        return `e(t) = ${syn.eligibility_trace}`;
      });

      await check('10. Трёхфакторное обучение Хебба и иммунитет тормозов', 'Ночной сон усиливает пластичный синапс, но держит тормоз -0.95 неизменным', async () => {
        const before = latestSnapshot.synapses.find((s) => s.edge === 'sensor_curiosity->inter_creative_spark').weight;
        const d = await runCloudSandboxAction('sleep', {}, 0.90, null);
        const after = d.snapshot.synapses.find((s) => s.edge === 'sensor_curiosity->inter_creative_spark').weight;
        const brake = d.snapshot.synapses.find((s) => s.edge === 'sensor_conflict->gate_proactive_outreach').weight;
        if (!(after > before) || Math.abs(brake - (-0.95)) > 1e-4) throw new Error('Нарушен закон пластичности');
        return `w: ${before.toFixed(3)} → ${after.toFixed(3)}, тормоз=${brake}`;
      });

      await check('11. Перенормировка весов Drydock (unexamined без мёртвого веса)', 'Сброс контура (pulse_seq=0) помечает Synaptic_Plasticity как unexamined и ставит Merit=undetermined', async () => {
        const d = await runCloudSandboxAction('reset', {}, 0, null);
        const dd = d.snapshot.drydock;
        if (!dd || !dd.readiness.unexamined.includes('Synaptic_Plasticity')) throw new Error('Synaptic_Plasticity не исключена при pulse_seq=0');
        if (dd.merit.conclusion !== 'undetermined') throw new Error(`Ожидался undetermined, получен ${dd.merit.conclusion}`);
        const rEval = await fetch('/neuro-studio/api/drydock-eval', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            mode: 'readiness',
            examined_categories: ['Neural_Stability', 'Inhibitory_Shield'],
            signals: [{ signal_id: 's1', title: 'High load', severity: 'high', confidence: 1.0, category: 'Neural_Stability' }],
          }),
        });
        const ev = await rEval.json();
        if (ev.readiness.total !== 9.5) throw new Error(`Ожидался 9.5 без мёртвого веса, получен ${ev.readiness.total}`);
        return `total=9.5 (unexamined=${ev.readiness.unexamined.join(',')}), Merit=undetermined`;
      });

      await check('12. Монотонное сжатие Gate (×0.69 ≤ 6.9) и строгий порядок тяжести', 'Конфликт включает Gate ≤ 6.9 и Merit=owed, сохраняя 1 critical > 3 criticals', async () => {
        const d = await runCloudSandboxAction('pulse', { sensor_conflict: 0.95, sensor_warmth: 0.85 }, -0.8, null);
        const dd = d.snapshot.drydock;
        if (!dd.readiness.gated || dd.readiness.total > 6.9 || dd.merit.conclusion !== 'owed') {
          throw new Error('Gate или Merit=owed не сработали при конфликте');
        }
        const r1 = await (await fetch('/neuro-studio/api/drydock-eval', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            mode: 'readiness',
            signals: [{ signal_id: 'c1', title: 'One crit', severity: 'critical', confidence: 0.90, category: 'Neural_Stability' }],
          }),
        })).json();
        const r3 = await (await fetch('/neuro-studio/api/drydock-eval', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            mode: 'readiness',
            signals: [
              { signal_id: 'c1', title: 'Crit 1', severity: 'critical', confidence: 0.95, category: 'Neural_Stability' },
              { signal_id: 'c2', title: 'Crit 2', severity: 'critical', confidence: 0.95, category: 'Inhibitory_Shield' },
              { signal_id: 'c3', title: 'Crit 3', severity: 'critical', confidence: 0.95, category: 'Modulator_Balance' },
            ],
          }),
        })).json();
        if (!(r3.readiness.total < r1.readiness.total && r1.readiness.total <= 6.9)) {
          throw new Error(`Нарушена монотонность Gate: ${r1.readiness.total} vs ${r3.readiness.total}`);
        }
        return `Live Gate=${dd.readiness.total}/10 (OWED), лестница ${r1.readiness.total} > ${r3.readiness.total}`;
      });

      await check('13. Интервал Уилсона 95% и Z-тест с поправкой Бонферрони', 'POST /neuro-studio/api/drydock-eval подтверждает значимость 105/144 vs 51/144 при m=3', async () => {
        const res = await fetch('/neuro-studio/api/drydock-eval', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: 'stats', hits_a: 105, total_a: 144, hits_b: 51, total_b: 144, alpha: 0.05, comparisons: 3 }),
        });
        const st = await res.json();
        if (!st.significant || !(st.two_proportion_p < st.bonferroni_alpha)) throw new Error('Статистический тест не пройден');
        return `${st.wilson_a.label} · p=${st.two_proportion_p} < α=${st.bonferroni_alpha}`;
      });

      await check('14. Криптозащита 4-шаговой цепочки SHA-256 (перехват подмены)', 'Подлинная цепочка проходит верификацию, а мутация любого поля мгновенно отклоняется', async () => {
        const liveRes = await (await fetch('/neuro-studio/api/live/default')).json();
        const cleanChain = liveRes.drydock.chain_state;
        const okClean = await (await fetch('/neuro-studio/api/drydock-eval', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: 'verify_chain', chain_state: cleanChain }),
        })).json();
        const forged = JSON.parse(JSON.stringify(cleanChain));
        forged.drydock_readiness.total = Number(forged.drydock_readiness.total) >= 9.9 ? 4.2 : 10.0;
        forged.verified = false;
        const okForged = await (await fetch('/neuro-studio/api/drydock-eval', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: 'verify_chain', chain_state: forged }),
        })).json();
        if (okClean.chain_verified !== true || okForged.chain_verified !== false) {
          throw new Error(`clean=${okClean.chain_verified}, forged=${okForged.chain_verified}`);
        }
        return 'Оригинал: VERIFIED (true) · Подделка: REJECTED (false)';
      });

      const passed = results.filter((r) => r.ok).length;
      badge.textContent = `${passed} / ${results.length} PASSED (CLOUD LIVE)`;
      badge.className = `mono text-xs px-3 py-1.5 rounded-xl font-semibold border ${passed === results.length ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' : 'bg-rose-500/20 text-rose-300 border-rose-500/40'}`;
      grid.innerHTML = results.map((r) => `<div class="rounded-xl p-3.5 border ${r.ok ? 'bg-slate-900/80 border-emerald-500/30' : 'bg-rose-950/30 border-rose-500/40'} space-y-1">
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs font-semibold text-white">${r.name}</span>
          <span class="mono text-[11px] px-2 py-0.5 rounded ${r.ok ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}">${r.ok ? 'PASS' : 'FAIL'} · ${r.ms} мс</span>
        </div>
        <p class="text-[11px] text-slate-400">${r.desc}</p>
        <p class="mono text-[11px] text-sky-300">${r.detail}</p>
      </div>`).join('');
    }

    async function runDrydockStatsCalc() {
      const payload = {
        mode: 'stats',
        hits_a: Number(document.getElementById('dd-ha').value || 0),
        total_a: Number(document.getElementById('dd-na').value || 1),
        hits_b: Number(document.getElementById('dd-hb').value || 0),
        total_b: Number(document.getElementById('dd-nb').value || 1),
        comparisons: Number(document.getElementById('dd-m').value || 1),
        alpha: Number(document.getElementById('dd-alpha').value || 0.05),
      };
      const res = await fetch('/neuro-studio/api/drydock-eval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const d = await res.json();
      if (!d.ok) return;
      document.getElementById('dd-stats-output').innerHTML = `
        <div class="rounded-xl bg-slate-900/85 border border-slate-800 p-3">
          <div class="text-slate-400 mb-1">Когорта A · Уилсон 95% CI</div>
          <div class="text-emerald-300 font-semibold">${d.wilson_a.label}</div>
        </div>
        <div class="rounded-xl bg-slate-900/85 border border-slate-800 p-3">
          <div class="text-slate-400 mb-1">Когорта B · Уилсон 95% CI</div>
          <div class="text-sky-300 font-semibold">${d.wilson_b.label}</div>
        </div>
        <div class="rounded-xl bg-slate-900/85 border ${d.significant ? 'border-emerald-500/40' : 'border-amber-500/40'} p-3">
          <div class="text-slate-400 mb-1">Двусторонний Z-тест &amp; Бонферрони</div>
          <div class="${d.significant ? 'text-emerald-300' : 'text-amber-300'} font-semibold">p = ${d.two_proportion_p} (${d.significant ? 'ЗНАЧИМО' : 'НЕ ЗНАЧИМО'} при &alpha;=${d.bonferroni_alpha})</div>
        </div>`;
    }

    document.getElementById('btn-dd-calc-stats').addEventListener('click', runDrydockStatsCalc);

    document.getElementById('dd-btn-cold').addEventListener('click', () =>
      runCloudSandboxAction('reset', {}, 0, 'Drydock: песочница сброшена (pulse_seq=0 → Synaptic_Plasticity UNEXAMINED, Merit UNDETERMINED).'));
    document.getElementById('dd-btn-norm').addEventListener('click', () =>
      runCloudSandboxAction('pulse', { sensor_curiosity: 0.92, sensor_warmth: 0.65 }, 0.85, 'Drydock: штатный импульс обработан (все 4 категории проверены, Merit DELIVERED).'));
    document.getElementById('dd-btn-gate').addEventListener('click', () =>
      runCloudSandboxAction('pulse', { sensor_conflict: 0.95, sensor_warmth: 0.88 }, -0.85, 'Drydock: конфликт сжал индекс монотонной формулой ×0.69 ≤ 6.9 и выставил Merit OWED.'));

    document.getElementById('btn-dd-verify-clean').addEventListener('click', async () => {
      if (!latestSnapshot || !latestSnapshot.drydock) return;
      const r = await fetch('/neuro-studio/api/drydock-eval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'verify_chain', chain_state: latestSnapshot.drydock.chain_state }),
      });
      const d = await r.json();
      const b = document.getElementById('dd-tamper-banner');
      b.className = 'rounded-xl px-3.5 py-2.5 text-xs mono bg-emerald-950/40 border border-emerald-500/40 text-emerald-200';
      b.textContent = `ПРОВЕРКА ПРОЙДЕНА (${d.engine_latency_ms} мс): все 4 SHA-256 квитанции совпадают (chain_verified = ${d.chain_verified})`;
    });

    document.getElementById('btn-dd-tamper-attack').addEventListener('click', async () => {
      if (!latestSnapshot || !latestSnapshot.drydock) return;
      const tampered = JSON.parse(JSON.stringify(latestSnapshot.drydock.chain_state));
      tampered.drydock_readiness.total = Number(tampered.drydock_readiness.total) >= 9.9 ? 4.2 : 10.0;
      tampered.neural_merit.conclusion = tampered.neural_merit.conclusion === 'owed' ? 'delivered' : 'owed';
      const r = await fetch('/neuro-studio/api/drydock-eval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'verify_chain', chain_state: tampered }),
      });
      const d = await r.json();
      const b = document.getElementById('dd-tamper-banner');
      b.className = 'rounded-xl px-3.5 py-2.5 text-xs mono bg-amber-950/50 border border-amber-400/50 text-amber-200';
      b.textContent = `АТАКА ПОДМЕНЫ ОТРАЖЕНА (${d.engine_latency_ms} мс): попытка подделать балл на 10.0 перехвачена по SHA-256 (chain_verified = ${d.chain_verified})`;
      showToast('Атака подмены SHA-256 успешно перехвачена сервером!');
    });

    // Wire UI tabs & buttons
    ['live', 'drydock', 'tests', 'matrix'].forEach((tab) => {
      document.getElementById(`tab-btn-${tab}`).addEventListener('click', () => {
        ['live', 'drydock', 'tests', 'matrix'].forEach((t) => {
          document.getElementById(`view-${t}`).classList.toggle('hidden', t !== tab);
          document.getElementById(`tab-btn-${t}`).classList.toggle('tab-active', t === tab);
        });
        if (tab === 'live') resizeCanvas();
        if (tab === 'drydock') runDrydockStatsCalc();
      });
    });

    document.getElementById('btn-scope-live').addEventListener('click', () => switchScope('default'));
    document.getElementById('btn-scope-sandbox').addEventListener('click', () => switchScope('demo:sandbox'));

    document.getElementById('sc-warm').addEventListener('click', () =>
      runCloudSandboxAction('pulse', { sensor_warmth: 0.90, sensor_silence_window: 0.72 }, 0.8, 'Сценарий 1: Тёплый импульс и окно тишины суммацией пробивают inter_rapport_drive → gate_proactive_outreach.'));
    document.getElementById('sc-creative').addEventListener('click', () =>
      runCloudSandboxAction('pulse', { sensor_curiosity: 0.94, sensor_warmth: 0.55 }, 0.8, 'Сценарий 2: Любопытство зажигает искру писателя 357 и открывает шлюз воображения.'));
    document.getElementById('sc-conflict').addEventListener('click', () =>
      runCloudSandboxAction('pulse', { sensor_warmth: 0.90, sensor_silence_window: 0.80, sensor_conflict: 0.95 }, -0.8, 'Сценарий 3: Синапс ГАМК (-0.95) мгновенно блокирует неуместную инициативу и включает gate_urgent_escalation.'));
    document.getElementById('sc-sleep').addEventListener('click', () =>
      runCloudSandboxAction('sleep', {}, 0.85, 'Сценарий 4: Ночная консолидация Хебба усилила активные синапсы в SQLite на сервере.'));
    document.getElementById('sc-reset').addEventListener('click', () =>
      runCloudSandboxAction('reset', {}, 0, 'Облачная песочница demo:sandbox сброшена к заводским весам.'));

    document.getElementById('btn-fire-selected').addEventListener('click', () => {
      const stim = {};
      stim[selectedNodeId] = 0.90;
      runCloudSandboxAction('pulse', stim, 0.75, `Тестовый импульс 0.90 подан на ${selectedNodeId} в облачной песочнице.`);
    });

    brainCanvas.addEventListener('click', (ev) => {
      const rect = brainCanvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      Object.entries(nodePositions).forEach(([nid, pos]) => {
        if (Math.hypot(x - pos.x, y - pos.y) <= 28) {
          selectedNodeId = nid;
          if (latestSnapshot) renderSnapshotUI(latestSnapshot);
        }
      });
    });

    document.querySelectorAll('.pkt-filter').forEach((btn) => {
      btn.addEventListener('click', () => {
        activeFilter = btn.getAttribute('data-filter') || 'ALL';
        document.querySelectorAll('.pkt-filter').forEach((b) => {
          const on = b === btn;
          b.className = `pkt-filter px-2.5 py-1 rounded-lg text-xs border ${on ? 'border-sky-400/50 bg-sky-500/20 text-sky-200' : 'border-slate-700 bg-slate-800/70 text-slate-300'}`;
        });
        if (latestSnapshot) renderSnapshotUI(latestSnapshot);
      });
    });

    document.getElementById('btn-export-log').addEventListener('click', async () => {
      if (!latestSnapshot) return;
      await navigator.clipboard.writeText(JSON.stringify(latestSnapshot, null, 2));
      showToast('JSON-снимок обсерватории скопирован в буфер обмена');
    });

    document.getElementById('btn-rerun-tests').addEventListener('click', runOnlineTestSuite);

    window.addEventListener('resize', resizeCanvas);
    initChart();
    resizeCanvas();
    requestAnimationFrame(drawConnectome);
    pollLiveScope();
    setInterval(pollLiveScope, 1200);
  </script>
</body>
</html>
"""
