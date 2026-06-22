from __future__ import annotations

from pathlib import Path

from .analysis import AnalysisResult
from .terminal import console, format_date_short


def generate_html(result: AnalysisResult) -> str:
    """Generate an interactive HTML visualization."""
    javascript_data: list[str] = []
    for history_file in result.files:
        if history_file.sequences:
            sequences_javascript = (
                "["
                + ", ".join(
                    f"{{start: {sequence.start_ts}, end: {sequence.end_ts}, count: {sequence.count}}}"
                    for sequence in history_file.sequences
                )
                + "]"
            )
            javascript_data.append(
                f'{{ name: "{history_file.name}", path: "{history_file.path.resolve()}", '
                f"start: {history_file.start_ts}, end: {history_file.end_ts}, "
                f'lines: {history_file.lines}, type: "{history_file.category}", sequences: {sequences_javascript} }}'
            )

    data_javascript = ",\n            ".join(javascript_data)

    main_history = next(
        (history_file for history_file in result.files if history_file.category == "main"),
        None,
    )
    earliest_file = min(
        (history_file for history_file in result.files if history_file.start_ts),
        key=lambda history_file: history_file.start_ts,
        default=None,
    )

    cleanliness_note_html = ""
    if result.dirty_file_count:
        cleanliness_note_html = """
              <p><strong>Note:</strong> one or more selected history files are not clean; optimal timeline may change after cleaning.</p>
          """

    gap_html = ""
    if main_history and earliest_file and main_history.start_ts and earliest_file.start_ts:
        gap_days = (main_history.start_ts - earliest_file.start_ts) // 86400
        if gap_days > 0:
            gap_html = f"""
              <p><strong>Main .zsh_history is missing {gap_days} days of history</strong> ({format_date_short(earliest_file.start_ts)} - {format_date_short(main_history.start_ts)})</p>
              """

    backups = [
        history_file
        for history_file in result.files
        if history_file.category != "main" and history_file.lines > 0
    ]
    largest_backup = max(backups, key=lambda history_file: history_file.lines) if backups else None

    recovery_html = ""
    if result.optimal_path:
        recovery_html += "<p><strong>Recommended Recovery Plan (Optimal Path):</strong></p>"
        recovery_html += "<ul style='margin-left: 20px; margin-top: 10px; font-family: monospace; font-size: 13px; color: #ccc;'>"
        for segment in result.optimal_path:
            duration = max(1, (segment.end_ts - segment.start_ts) // 86400)
            recovery_html += (
                f"<li>"
                f"<span style='color: #888'>{format_date_short(segment.start_ts)} - {format_date_short(segment.end_ts)}</span>"
                f" <span style='color: #555'>({duration}d)</span>: "
                f"<span class='recovery-source' data-path='{segment.file.path.resolve()}' style='color: #4facfe; cursor: pointer; transition: all 0.2s; border-bottom: 1px dashed transparent;'>{segment.file.name}</span>"
                f"</li>"
            )
        recovery_html += "</ul>"
        recovery_html += """
          <style>
              .recovery-source:hover {
                  color: #fff !important;
                  border-bottom: 1px dashed #fff !important;
                  text-shadow: 0 0 8px rgba(79, 172, 254, 0.6);
              }
          </style>
          """
    elif largest_backup:
        recovery_html = f"""
              <p><strong>Best single recovery source:</strong> <code>{largest_backup.name}</code> ({largest_backup.lines:,} lines)</p>
          """

    optimal_sequences: list[str] = []
    for segment in result.optimal_path or []:
        optimal_sequences.append(
            f"{{start: {segment.start_ts}, end: {segment.end_ts}, count: 0, "
            f"sourceName: '{segment.file.name}', sourcePath: '{segment.file.path.resolve()}'}}"
        )

    optimal_sequence_javascript = "[" + ", ".join(optimal_sequences) + "]"

    if result.optimal_path:
        optimal_lines = sum(segment.file.lines for segment in result.optimal_path)
        optimal_entry = (
            f'{{ name: "✨ Best Recovery Path", path: "", '
            f"start: {result.optimal_path[0].start_ts}, end: {result.optimal_path[-1].end_ts}, "
            f'lines: {optimal_lines}, type: "optimal", sequences: {optimal_sequence_javascript} }}'
        )
        data_javascript = optimal_entry + ",\n            " + data_javascript

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ZSH History Timeline Analysis</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            padding: 20px;
        }}
        .container {{ width: 95%; margin: 0 auto; }}
        h1 {{ font-size: 28px; margin-bottom: 10px; color: #fff; }}
        .summary {{
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            border-left: 4px solid #f44336;
        }}
        .summary h2 {{ font-size: 18px; margin-bottom: 10px; color: #f44336; }}
        .summary p {{ margin: 8px 0; line-height: 1.6; }}
        .chart-container {{
            background: #2a2a2a;
            border-radius: 8px;
            padding: 30px;
            overflow-x: auto;
        }}
        .timeline {{ position: relative; min-width: 1200px; }}
        .timeline-row {{
            display: flex;
            align-items: center;
            margin-bottom: 8px;
            min-height: 40px;
        }}
        .file-label {{
            width: 350px;
            font-size: 12px;
            font-family: 'Monaco', 'Menlo', monospace;
            padding-right: 20px;
            flex-shrink: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .timeline-track {{
            position: relative;
            flex: 1;
            height: 32px;
            background: #1a1a1a;
            border-radius: 4px;
        }}
        .timeline-bar {{
            position: absolute;
            height: 100%;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            padding: 0 8px;
            font-size: 11px;
            font-weight: 500;
            overflow: hidden;
        }}
        .timeline-bar:hover {{
            filter: brightness(1.3);
            z-index: 10;
            transform: scaleY(1.15);
        }}
        .overlay-container {{
            position: absolute;
            top: 0;
            bottom: 0;
            left: 350px;
            right: 0;
            pointer-events: none;
            z-index: 20;
        }}
        .timeline-marker {{
            position: absolute;
            top: 0;
            bottom: 0;
            width: 1px;
            background: rgba(255, 255, 255, 0.1);
            transform: translateX(-50%);
            pointer-events: auto;
            transition: width 0.1s, background 0.1s;
        }}
        .timeline-marker.aligned {{
            background: rgba(0, 255, 0, 0.5);
            width: 1px;
            z-index: 30;
        }}
        .timeline-marker:hover,
        .timeline-marker.active {{
            background: #fff;
            width: 2px;
            z-index: 40;
            box-shadow: 0 0 4px rgba(255,255,255,0.5);
        }}
        .timeline-bar.related {{
            box-shadow: 0 0 15px 3px rgba(255, 255, 255, 0.6);
            filter: brightness(1.4);
            transform: scaleY(1.15);
            border: 1px solid rgba(255, 255, 255, 0.9);
            z-index: 15;
        }}
        .cat-main {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: 2px solid #8b9aff;
        }}
        .cat-timestamped {{
            background: linear-gradient(135deg, #ff9a56 0%, #ffcd39 100%);
            border: 2px solid #ffa726;
        }}
        .cat-clean {{
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        }}
        .cat-snapshot {{
            background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
        }}
        .cat-other {{
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
        }}
        .cat-optimal {{
            background: linear-gradient(135deg, #ff0844 0%, #ffb199 100%);
            border: 2px solid #ff4b4b;
            box-shadow: 0 0 10px rgba(255, 75, 75, 0.3);
        }}
        .date-axis {{
            display: flex;
            margin-left: 350px;
            margin-top: 10px;
            border-top: 2px solid #444;
            padding-top: 10px;
            position: relative;
            height: 30px;
        }}
        .date-marker {{
            position: absolute;
            font-size: 11px;
            color: #999;
            white-space: nowrap;
            transform: translateX(-50%);
        }}
        .tooltip {{
            position: fixed;
            background: #333;
            color: #fff;
            padding: 12px 16px;
            border-radius: 6px;
            font-size: 12px;
            pointer-events: auto;
            z-index: 1000;
            display: none;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            border: 1px solid #555;
            max-width: 400px;
        }}
        .tooltip-visible {{ display: block; }}
        .legend {{
            margin-top: 20px;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
        }}
        .legend-color {{
            width: 24px;
            height: 16px;
            border-radius: 3px;
        }}
        .stats {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #444;
            font-size: 13px;
            color: #aaa;
        }}
        .chart-container::-webkit-scrollbar {{
            width: 12px;
            height: 12px;
        }}
        .chart-container::-webkit-scrollbar-track {{
            background: #2a2a2a;
            border-radius: 8px;
        }}
        .chart-container::-webkit-scrollbar-thumb {{
            background: #555;
            border-radius: 6px;
            border: 3px solid #2a2a2a;
        }}
        .chart-container::-webkit-scrollbar-thumb:hover {{
            background: #777;
        }}
        .chart-container::-webkit-scrollbar-corner {{
            background: #2a2a2a;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🕐 ZSH History Timeline</h1>

        <div class="summary">
            <h2>Analysis Results</h2>
            {cleanliness_note_html}
            {gap_html}
            {recovery_html}
            <div class="stats">
                <p>Total files analyzed: {len(result.files)}</p>
            </div>
        </div>

        <div class="chart-container">
            <div class="timeline" id="timeline"></div>

            <div class="legend">
                <div class="legend-item">
                    <div class="legend-color cat-main"></div>
                    <span>Main .zsh_history</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color cat-timestamped"></div>
                    <span>.zsh_history_backups/</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color cat-clean"></div>
                    <span>Explicit .zsh_hist.clean.*</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color cat-snapshot"></div>
                    <span>.zsh_history.* snapshots</span>
                </div>
            </div>
        </div>
    </div>

    <div class="tooltip" id="tooltip"></div>

    <script>
        const data = [
            {data_javascript}
        ];

        const minTime = Math.min(...data.map(d => d.start));
        const maxTime = Math.max(...data.map(d => d.end));
        const timeRange = maxTime - minTime;

        function formatDate(timestamp) {{
            const date = new Date(timestamp * 1000);
            return date.toLocaleDateString('en-US', {{ month: 'short', day: 'numeric', year: 'numeric' }});
        }}

        function formatDateTime(timestamp) {{
            const date = new Date(timestamp * 1000);
            return date.toLocaleString('en-US', {{
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            }});
        }}

        function calculatePosition(timestamp) {{
            return ((timestamp - minTime) / timeRange) * 100;
        }}

        const timeline = document.getElementById('timeline');
        const tooltip = document.getElementById('tooltip');
        let hideTimeout;

        const MIN_PX_PER_DAY = 20;
        const totalDays = timeRange / 86400;
        const requiredTrackWidth = Math.max(800, totalDays * MIN_PX_PER_DAY);
        const labelWidth = 350;
        const totalWidth = labelWidth + requiredTrackWidth;

        timeline.style.minWidth = `${{totalWidth}}px`;

        tooltip.addEventListener('mouseenter', () => {{
            if (hideTimeout) clearTimeout(hideTimeout);
        }});

        tooltip.addEventListener('mouseleave', () => {{
            tooltip.classList.remove('tooltip-visible');
        }});

        const overlay = document.createElement('div');
        overlay.className = 'overlay-container';
        timeline.appendChild(overlay);

        const points = {{}};
        data.forEach(d => {{
            if (d.sequences) {{
                d.sequences.forEach(seq => {{
                    if (!points[seq.start]) points[seq.start] = [];
                    points[seq.start].push({{name: d.name, type: '[start]'}});

                    if (!points[seq.end]) points[seq.end] = [];
                    points[seq.end].push({{name: d.name, type: '[end]'}});
                }});
            }} else {{
                if (!points[d.start]) points[d.start] = [];
                points[d.start].push({{name: d.name, type: '[start]'}});
                if (!points[d.end]) points[d.end] = [];
                points[d.end].push({{name: d.name, type: '[end]'}});
            }}
        }});

        const sortedData = [...data].sort((a, b) => {{
            if (a.type === 'main') return -1;
            if (b.type === 'main') return 1;
            if (a.type === 'timestamped' && b.type !== 'timestamped') return -1;
            if (b.type === 'timestamped' && a.type !== 'timestamped') return 1;
            return a.start - b.start;
        }});

        sortedData.forEach(item => {{
            const row = document.createElement('div');
            row.className = 'timeline-row';

            const label = document.createElement('div');
            label.className = 'file-label';
            label.textContent = item.name;
            label.title = item.name;

            const track = document.createElement('div');
            track.className = 'timeline-track';

            const sequences = item.sequences && item.sequences.length > 0
                ? item.sequences
                : [{{start: item.start, end: item.end, count: item.lines}}];

            sequences.forEach(seq => {{
                const bar = document.createElement('div');
                bar.className = `timeline-bar cat-${{item.type}}`;

                const left = calculatePosition(seq.start);
                const width = calculatePosition(seq.end) - left;

                bar.style.left = `${{left}}%`;
                bar.style.width = `${{width}}%`;
                bar.dataset.start = seq.start;
                bar.dataset.end = seq.end;

                const itemPath = seq.sourcePath || item.path;
                bar.dataset.path = itemPath;

                const durationDays = Math.max(1, Math.round((seq.end - seq.start) / 86400));
                bar.textContent = durationDays > 5 ? `${{durationDays}}d` : '';

                bar.addEventListener('click', () => {{
                    window.location.href = `cursor://file${{itemPath}}`;
                }});

                bar.addEventListener('mouseenter', () => {{
                    if (hideTimeout) clearTimeout(hideTimeout);

                    const allBars = document.querySelectorAll('.timeline-bar');
                    allBars.forEach(otherBar => {{
                        if (otherBar === bar) return;
                        const otherStart = parseInt(otherBar.dataset.start);
                        const otherEnd = parseInt(otherBar.dataset.end);
                        if (otherStart === seq.start || otherStart === seq.end || otherEnd === seq.start || otherEnd === seq.end) {{
                            otherBar.classList.add('related');
                        }}
                    }});

                    [seq.start, seq.end].forEach(timestamp => {{
                        const marker = document.querySelector(`.timeline-marker[data-ts="${{timestamp}}"]`);
                        if (marker && marker.classList.contains('aligned')) {{
                            marker.classList.add('active');
                        }}
                    }});

                    const rect = bar.getBoundingClientRect();
                    const title = seq.sourceName ? `Expected Source: ${{seq.sourceName}}` : item.name;
                    const subtitle = seq.sourcePath || item.path;

                    tooltip.innerHTML = `
                        <strong>${{title}}</strong><br>
                        <span style="font-family: monospace; font-size: 10px; color: #aaa">${{subtitle}}</span><br>
                        Sequence Start: ${{formatDateTime(seq.start)}}<br>
                        Sequence End: ${{formatDateTime(seq.end)}}<br>
                        Seq Duration: ${{durationDays}} days<br>
                        Seq Events: ${{seq.count ? seq.count.toLocaleString() : 'N/A'}}<hr style="border:0; border-top:1px solid #555; margin:5px 0">
                        Total Lines: ${{item.lines.toLocaleString()}}
                    `;
                    tooltip.style.left = `${{rect.left}}px`;
                    tooltip.style.top = `${{rect.top - tooltip.offsetHeight - 10}}px`;
                    tooltip.classList.add('tooltip-visible');
                }});

                bar.addEventListener('mouseleave', () => {{
                    document.querySelectorAll('.timeline-bar.related').forEach(otherBar => {{
                        otherBar.classList.remove('related');
                    }});
                    document.querySelectorAll('.timeline-marker.active').forEach(marker => {{
                        marker.classList.remove('active');
                    }});
                    hideTimeout = setTimeout(() => {{
                        tooltip.classList.remove('tooltip-visible');
                    }}, 300);
                }});

                track.appendChild(bar);
            }});

            row.appendChild(label);
            row.appendChild(track);
            timeline.appendChild(row);
        }});

        document.querySelectorAll('.recovery-source').forEach(element => {{
            element.addEventListener('mouseenter', () => {{
                const path = element.dataset.path;
                if (!path) return;

                document.querySelectorAll('.timeline-bar').forEach(bar => {{
                    if (bar.dataset.path === path) {{
                        bar.classList.add('related');
                    }}
                }});
            }});

            element.addEventListener('mouseleave', () => {{
                 document.querySelectorAll('.timeline-bar.related').forEach(bar => {{
                    bar.classList.remove('related');
                }});
            }});
        }});

        Object.keys(points).forEach(timestamp => {{
            const marker = document.createElement('div');
            const isAligned = points[timestamp].length > 1;

            marker.className = `timeline-marker ${{isAligned ? 'aligned' : ''}}`;
            marker.style.left = `${{calculatePosition(timestamp)}}%`;
            marker.dataset.ts = timestamp;

            marker.addEventListener('mouseenter', event => {{
                event.preventDefault();
                event.stopPropagation();
                if (hideTimeout) clearTimeout(hideTimeout);

                const allBars = document.querySelectorAll('.timeline-bar');
                allBars.forEach(bar => {{
                    const barStart = bar.dataset.start;
                    const barEnd = bar.dataset.end;
                    if (barStart == timestamp || barEnd == timestamp) {{
                        bar.classList.add('related');
                    }}
                }});

                const rect = marker.getBoundingClientRect();
                const shared = points[timestamp];
                let html = shared.map(point => `${{point.name}} ${{point.type}}`).join('<br>');
                html += `<br><br><span style="color: #aaa">${{formatDateTime(timestamp)}}</span>`;

                tooltip.innerHTML = html;
                tooltip.style.left = `${{rect.left + 10}}px`;
                tooltip.style.top = `${{rect.top - 10}}px`;
                tooltip.classList.add('tooltip-visible');
            }});

            marker.addEventListener('mouseleave', () => {{
                document.querySelectorAll('.timeline-bar.related').forEach(bar => {{
                    bar.classList.remove('related');
                }});

                hideTimeout = setTimeout(() => {{
                    tooltip.classList.remove('tooltip-visible');
                }}, 300);
            }});

            overlay.appendChild(marker);
        }});

        const dateAxis = document.createElement('div');
        dateAxis.className = 'date-axis';
        dateAxis.id = 'dateAxis';
        timeline.appendChild(dateAxis);

        const markerCount = 10;
        for (let index = 0; index <= markerCount; index++) {{
            const timestamp = minTime + (timeRange / markerCount) * index;
            const marker = document.createElement('div');
            marker.className = 'date-marker';
            marker.textContent = formatDate(timestamp);
            marker.style.left = `${{(index / markerCount) * 100}}%`;
            dateAxis.appendChild(marker);
        }}
    </script>
</body>
</html>"""


def output_html(result: AnalysisResult, path: Path) -> None:
    """Write the HTML visualization to a file."""
    html = generate_html(result)
    path.write_text(html, encoding="utf-8")
    console.print(f"[green]✓[/green] HTML written to {path}")
