$env:PYTHONPATH='C:\Users\21986\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages;C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\src'
$env:PYTHONIOENCODING='utf-8'
& 'C:\Users\21986\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c 'from ai_pr_review.web_server import serve; from ai_pr_review.config import AppConfig; serve(AppConfig.load(), host="127.0.0.1", port=8787)'
