"""
日本政治ブリーフィング HTML生成スクリプト
毎日のMarkdownファイルから配信用HTMLページを自動生成します。

使い方:
  python generate_html.py <markdownファイルパス>
  python generate_html.py            # 最新のMarkdownを自動選択
  python generate_html.py --all      # 同フォルダ内すべてのMarkdownを一括変換
"""

import sys
import os
import re
from datetime import datetime


def parse_markdown(md_text):
    """MarkdownからセクションとメタデータをParseする（堅牢版）"""
    title = ''
    date_str = ''
    summary = ''
    topics = []
    points = []
    sources = []

    current_topic = None
    current_section = None
    state = None

    def finalize_topic():
        nonlocal current_topic, current_section
        if current_topic:
            topics.append(current_topic)
            current_topic = None
            current_section = None

    for raw_line in md_text.split('\n'):
        line = raw_line
        stripped = line.strip()

        # ---- セクション見出し（先に処理して状態遷移を確実に） ----

        # タイトル行（H1）
        if line.startswith('# ') and not line.startswith('## '):
            title = line[2:].strip()
            m = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', title)
            if m:
                date_str = m.group(1)
            continue

        # サマリー
        if '今日のひとことサマリー' in line:
            finalize_topic()
            state = 'summary'
            continue

        # トピック見出し「## 1. ...」「### 1. ...」両対応
        if re.match(r'^#{2,3}\s+\d+\.', line):
            finalize_topic()
            title_text = re.sub(r'^#{2,3}\s+\d+\.\s*', '', line).strip()
            current_topic = {'title': title_text, 'fact': '', 'context': '', 'implication': ''}
            current_section = None
            state = 'topic'
            continue

        # ポイント見出し（新旧両対応）
        if re.match(r'^##\s+(💡\s*)?(ポイント|講演で使えるポイント)\s*$', line):
            finalize_topic()
            state = 'points'
            continue

        # 出典見出し
        if re.match(r'^##\s+出典\s*$', line):
            finalize_topic()
            state = 'sources'
            continue

        # その他の ## 見出し（カテゴリ未指定）→ 状態クリア
        if line.startswith('## '):
            finalize_topic()
            state = None
            continue

        # 区切り線
        if stripped == '---':
            # トピック内は終わり、次のセクション見出しを待つ
            continue

        # ---- 状態別の本文処理 ----

        if state == 'summary':
            if stripped:
                summary += stripped + ' '
            continue

        if state == 'topic' and current_topic:
            # 「事実」「何が起きたか」両対応
            if re.search(r'\*\*(何が起きたか|事実)\*\*', line):
                current_section = 'fact'
                # ラベル行に本文が同居している場合に対応
                tail = re.sub(r'^.*\*\*(?:何が起きたか|事実)\*\*[:：]?\s*', '', stripped)
                if tail:
                    current_topic['fact'] += tail + ' '
                continue
            if re.search(r'\*\*背景[・･]?文脈\*\*', line):
                current_section = 'context'
                tail = re.sub(r'^.*\*\*背景[・･]?文脈\*\*[:：]?\s*', '', stripped)
                if tail:
                    current_topic['context'] += tail + ' '
                continue
            if re.search(r'\*\*経済[・･]?(政策|市場)への含意\*\*', line):
                current_section = 'implication'
                tail = re.sub(r'^.*\*\*経済[・･]?(?:政策|市場)への含意\*\*[:：]?\s*', '', stripped)
                if tail:
                    current_topic['implication'] += tail + ' '
                continue
            if current_section and stripped and not stripped.startswith('#'):
                current_topic[current_section] += stripped + ' '
            continue

        if state == 'points':
            if not stripped:
                continue
            # 形式A:「1. **タイトル** ——本文」「1. **タイトル** 本文」（1行完結）
            m = re.match(
                r'^(?:\d+\.|-)\s*\*\*(.+?)\*\*\s*(?:[—–\-]+)?\s*(.+)$',
                stripped,
            )
            if m:
                points.append({'title': m.group(1).strip(), 'text': m.group(2).strip()})
                continue
            # 形式B:「**1. タイトル**」だけの行（本文は次行以降）
            m = re.match(r'^\*\*\s*(\d+\.\s*.+?)\s*\*\*\s*$', stripped)
            if m:
                title = re.sub(r'^\d+\.\s*', '', m.group(1)).strip()
                points.append({'title': title, 'text': ''})
                continue
            # 形式C:「**タイトル**」だけの行（番号なし）
            m = re.match(r'^\*\*\s*(.+?)\s*\*\*\s*$', stripped)
            if m:
                points.append({'title': m.group(1).strip(), 'text': ''})
                continue
            # 形式D: 番号付きで太字なし（1行）
            m = re.match(r'^(?:\d+\.|-)\s*(.+)$', stripped)
            if m:
                points.append({'title': '', 'text': m.group(1).strip()})
                continue
            # 形式E: 直前のポイントの本文（追記）
            if points and not stripped.startswith('#'):
                sep = ' ' if points[-1]['text'] else ''
                points[-1]['text'] = (points[-1]['text'] + sep + stripped).strip()
            continue

        if state == 'sources':
            m = re.match(r'^-\s*\[(.+?)\]\((.+?)\)', stripped)
            if m:
                sources.append({'text': m.group(1).strip(), 'url': m.group(2).strip()})
            continue

    finalize_topic()

    return {
        'title': title,
        'date': date_str,
        'summary': summary.strip(),
        'topics': topics,
        'points': points,
        'sources': sources,
    }


def html_escape(s):
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;'))


def generate_html(data):
    """パースデータからHTMLを生成"""

    topics_html = ''
    for i, t in enumerate(data['topics'], 1):
        implication_block = ''
        if t.get('implication', '').strip():
            implication_block = f'''
        <div class="implication-section">
          <div class="section-label label-implication">経済・政策への含意</div>
          <p>{t["implication"].strip()}</p>
        </div>'''

        context_block = ''
        if t.get('context', '').strip():
            context_block = f'''
        <div class="context-section">
          <div class="section-label label-context">背景・文脈</div>
          <p>{t["context"].strip()}</p>
        </div>'''

        fact_block = ''
        if t.get('fact', '').strip():
            fact_block = f'''
        <div class="fact-section">
          <div class="section-label label-fact">事実</div>
          <p>{t["fact"].strip()}</p>
        </div>'''

        topics_html += f'''
  <div class="topic-card" id="topic{i}">
    <div class="topic-number">TOPIC {i:02d}</div>
    <h2 class="topic-title">{t["title"]}</h2>
    {fact_block}
    {context_block}
    {implication_block}
  </div>
'''

    points_html = ''
    for i, p in enumerate(data['points'], 1):
        title_part = f'<strong>{p["title"]}</strong>　' if p['title'] else ''
        points_html += f'''
    <div class="point-item">
      <div class="point-num">{i}</div>
      <div class="point-text">{title_part}{p["text"]}</div>
    </div>'''

    sources_html = ''
    for s in data['sources']:
        sources_html += f'<li><a href="{s["url"]}" target="_blank" rel="noopener">{s["text"]}</a></li>\n'

    toc_html = ''.join([f'<li><a href="#topic{i+1}">{t["title"][:15]}...</a></li>' for i, t in enumerate(data['topics'])])

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>日本政治ブリーフィング｜{data['date']}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght@400;600;700&family=Noto+Sans+JP:wght@300;400;500;700&display=swap');
  :root {{
    --primary:#1a1a2e;--accent:#c0392b;--gold:#d4a017;
    --bg:#f8f6f1;--card-bg:#fff;--text:#2c2c2c;
    --text-light:#666;--border:#e0dbd0;--tag-bg:#f0ece3;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Noto Sans JP',sans-serif;background:var(--bg);color:var(--text);line-height:1.8;font-size:15px}}
  header{{background:var(--primary);color:white;position:sticky;top:0;z-index:100;box-shadow:0 2px 12px rgba(0,0,0,.3)}}
  .header-inner{{max-width:900px;margin:0 auto;padding:16px 24px;display:flex;align-items:center;justify-content:space-between}}
  .header-logo{{font-family:'Noto Serif JP',serif;font-size:13px;font-weight:600;letter-spacing:.15em;color:rgba(255,255,255,.7);text-transform:uppercase}}
  .header-date{{font-size:13px;color:rgba(255,255,255,.55)}}
  .hero{{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 60%,#0f3460 100%);color:white;padding:56px 24px 48px;text-align:center}}
  .hero-eyebrow{{font-size:11px;letter-spacing:.25em;text-transform:uppercase;color:var(--gold);margin-bottom:16px;font-weight:500}}
  .hero-title{{font-family:'Noto Serif JP',serif;font-size:clamp(22px,4vw,32px);font-weight:700;line-height:1.4;margin-bottom:12px}}
  .hero-date-badge{{display:inline-block;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:20px;padding:4px 16px;font-size:12px;color:rgba(255,255,255,.7);margin-bottom:32px}}
  .summary-box{{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.15);border-left:3px solid var(--gold);border-radius:6px;padding:20px 24px;max-width:700px;margin:0 auto;text-align:left;font-size:14.5px;line-height:1.85;color:rgba(255,255,255,.88)}}
  .summary-label{{font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:var(--gold);margin-bottom:8px;font-weight:600}}
  main{{max-width:900px;margin:0 auto;padding:40px 24px 60px}}
  .toc{{background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:20px 24px;margin-bottom:36px}}
  .toc-title{{font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--text-light);margin-bottom:12px;font-weight:600}}
  .toc-list{{list-style:none;display:flex;flex-wrap:wrap;gap:8px}}
  .toc-list a{{display:inline-block;background:var(--tag-bg);color:var(--text);text-decoration:none;font-size:12px;padding:5px 12px;border-radius:4px;border:1px solid var(--border);transition:all .15s}}
  .toc-list a:hover{{background:var(--primary);color:white;border-color:var(--primary)}}
  .topic-card{{background:var(--card-bg);border:1px solid var(--border);border-radius:10px;padding:28px 32px;margin-bottom:24px;position:relative;overflow:hidden;transition:box-shadow .2s}}
  .topic-card:hover{{box-shadow:0 4px 20px rgba(0,0,0,.08)}}
  .topic-card::before{{content:'';position:absolute;top:0;left:0;width:4px;height:100%;background:var(--accent)}}
  .topic-number{{font-size:11px;color:var(--accent);font-weight:700;letter-spacing:.1em;margin-bottom:6px}}
  .topic-title{{font-family:'Noto Serif JP',serif;font-size:18px;font-weight:700;color:var(--primary);margin-bottom:20px;line-height:1.4}}
  .fact-section,.context-section,.implication-section{{margin-bottom:16px}}
  .section-label{{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;padding:3px 10px;border-radius:3px;margin-bottom:8px}}
  .label-fact{{background:#eef2ff;color:#3730a3}}
  .label-context{{background:#f0fdf4;color:#166534}}
  .label-implication{{background:#fffbeb;color:#92400e}}
  .fact-section p,.context-section p,.implication-section p{{font-size:14.5px;line-height:1.85}}
  .points-card{{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);border-radius:10px;padding:28px 32px;margin-bottom:24px;color:white}}
  .points-title{{font-family:'Noto Serif JP',serif;font-size:16px;font-weight:700;color:var(--gold);margin-bottom:20px}}
  .point-item{{display:flex;gap:14px;margin-bottom:16px;padding:16px;background:rgba(255,255,255,.06);border-radius:6px;border:1px solid rgba(255,255,255,.1)}}
  .point-num{{flex-shrink:0;width:24px;height:24px;background:var(--gold);color:var(--primary);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;margin-top:2px}}
  .point-text{{font-size:14px;line-height:1.8;color:rgba(255,255,255,.88)}}
  .point-text strong{{color:white;font-weight:600}}
  .sources-section{{background:var(--card-bg);border:1px solid var(--border);border-radius:10px;padding:24px 32px;margin-bottom:24px}}
  .sources-title{{font-size:13px;font-weight:700;letter-spacing:.1em;color:var(--text-light);text-transform:uppercase;margin-bottom:14px}}
  .source-list{{list-style:none;display:flex;flex-direction:column;gap:6px}}
  .source-list li::before{{content:'→';color:var(--accent);margin-right:8px;font-size:12px}}
  .source-list a{{color:#2563eb;text-decoration:none;font-size:13px;word-break:break-all}}
  .source-list a:hover{{text-decoration:underline}}
  footer{{background:var(--primary);color:rgba(255,255,255,.5);text-align:center;padding:24px;font-size:12px}}
  @media(max-width:600px){{.hero{{padding:40px 16px 36px}}.topic-card,.points-card,.sources-section{{padding:20px 18px}}main{{padding:24px 14px 48px}}}}
</style>
</head>
<body>
<header>
  <div class="header-inner">
    <div class="header-logo">日本政治ブリーフィング</div>
    <div class="header-date">{data['date']}</div>
  </div>
</header>
<div class="hero">
  <div class="hero-eyebrow">Japan Politics Daily Briefing</div>
  <h1 class="hero-title">日本政治ブリーフィング</h1>
  <div class="hero-date-badge">{data['date']}</div>
  <div class="summary-box">
    <div class="summary-label">Today's Summary · 今日のひとことサマリー</div>
    {data['summary']}
  </div>
</div>
<main>
  <nav class="toc">
    <div class="toc-title">Topics</div>
    <ul class="toc-list">{toc_html}<li><a href="#points">ポイント</a></li></ul>
  </nav>
  {topics_html}
  <div class="points-card" id="points">
    <div class="points-title">💡 ポイント</div>
    {points_html}
  </div>
  <div class="sources-section">
    <div class="sources-title">出典 · Sources</div>
    <ul class="source-list">{sources_html}</ul>
  </div>
</main>
<footer>
  <p>日本政治ブリーフィング · Japan Politics Daily Briefing · {data['date']}</p>
  <p style="margin-top:6px;">For Yoshii · ビジネス・専門家向け講演準備</p>
</footer>
</body>
</html>"""
    return html


def process_one(md_path, update_index=True):
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    data = parse_markdown(md_text)

    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', data['date'])
    if m:
        date_for_filename = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    else:
        m2 = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(md_path))
        date_for_filename = m2.group(1) if m2 else datetime.today().strftime('%Y-%m-%d')

    html = generate_html(data)

    output_dir = os.path.dirname(md_path)
    output_path = os.path.join(output_dir, f"{date_for_filename}.html")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"OK HTML: {output_path}  (topics={len(data['topics'])}, points={len(data['points'])}, sources={len(data['sources'])})")

    if not update_index:
        return

    index_path = os.path.join(output_dir, 'index.html')
    if not os.path.exists(index_path):
        return
    with open(index_path, 'r', encoding='utf-8') as f:
        index_html = f.read()

    if date_for_filename in index_html:
        return  # 既にあれば触らない

    new_card = f"""    <a class="briefing-card" href="{date_for_filename}.html">
      <div class="card-date">{data['date']}<span class="latest-badge">Latest</span></div>
      <div class="card-summary">{data['summary'][:100]}...</div>
      <div class="card-arrow">このブリーフィングを読む →</div>
    </a>

"""
    index_html = index_html.replace('<span class="latest-badge">Latest</span>', '')
    grid_marker = '<div class="briefing-grid">'
    index_html = index_html.replace(grid_marker, grid_marker + '\n\n' + new_card, 1)
    count = len(re.findall(r'<a class="briefing-card"', index_html))
    index_html = re.sub(r'バックナンバー一覧（\d+号）',
                        f'バックナンバー一覧（{count}号）', index_html)
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_html)
    print(f"  index.html updated (total {count})")


def main():
    args = sys.argv[1:]
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if '--all' in args:
        md_files = sorted([f for f in os.listdir(script_dir)
                           if f.startswith('日本政治ブリーフィング_') and f.endswith('.md')])
        if not md_files:
            print('エラー: Markdownファイルが見つかりません')
            sys.exit(1)
        for name in md_files:
            process_one(os.path.join(script_dir, name), update_index=False)
        print(f'== 全 {len(md_files)} 本を再生成しました ==')
        return

    if not args:
        md_files = sorted([f for f in os.listdir(script_dir)
                           if f.startswith('日本政治ブリーフィング_') and f.endswith('.md')],
                          reverse=True)
        if not md_files:
            print('エラー: Markdownファイルが見つかりません')
            sys.exit(1)
        md_path = os.path.join(script_dir, md_files[0])
        print(f'最新ファイルを使用: {md_files[0]}')
    else:
        md_path = args[0]
        if not os.path.isabs(md_path):
            md_path = os.path.join(script_dir, md_path)

    if not os.path.exists(md_path):
        print(f'エラー: ファイルが見つかりません: {md_path}')
        sys.exit(1)

    process_one(md_path)


if __name__ == '__main__':
    main()
