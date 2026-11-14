import argparse
import json
from pathlib import Path
from model import pipeline, score_truth


def evaluate(data_path, truth_path=None):
    result = pipeline(Path(data_path).read_bytes())
    report = {k: v for k, v in result.items() if k not in ('test_rows', 'fitted_parameters')}
    if truth_path is not None:
        report['synthetic_truth_metrics'] = score_truth(result, json.loads(Path(truth_path).read_text(encoding='utf-8')))
    report['flagged_hours'] = sum(r['flagged'] for r in result['test_rows'])
    report['event_count'] = len(result['events'])
    report['limits'] = 'Synthetic hourly one-step backtest, not live meter monitoring, fault diagnosis, cost savings or guaranteed interval coverage.'
    return report


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default=str(root / 'data/hourly_demo.csv'))
    parser.add_argument('--truth', help='Optional separate truth JSON for this exact CSV')
    parser.add_argument('--output', default='reports/evaluation.json')
    args = parser.parse_args()
    # Default demo labels only when using the default bundled CSV.
    truth = args.truth
    if truth is None and Path(args.data).resolve() == (root / 'data/hourly_demo.csv').resolve():
        truth = root / 'data/truth.json'
    report = evaluate(args.data, truth)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('selected_model', 'test_metrics_all_observed', 'flagged_hours', 'event_count', 'synthetic_truth_metrics') if key in report}, indent=2))
    print(f'Report: {output}')
