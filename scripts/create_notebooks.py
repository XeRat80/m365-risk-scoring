#!/usr/bin/env python3
"""Create the five parameterized, output-clean analysis notebooks."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ROOT / "notebooks"


def notebook(title: str, cells: list[object]) -> object:
    book = nbf.v4.new_notebook()
    book["metadata"]["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    book["metadata"]["m365risk"] = {"privacy": "headers-and-metadata-only", "parameterized": True}
    book["cells"] = [
        nbf.v4.new_markdown_cell(
            f"# {title}\n\nPrivacy rule: no subject, body, preview, or attachment content is loaded."
        ),
        cells[0],
        PATHS,
        *cells[1:],
    ]
    return book


PARAMETERS = nbf.v4.new_code_cell(
    "PROJECT_ROOT = '..'\nRANDOM_SEED = 365",
    metadata={"tags": ["parameters"]},
)
PATHS = nbf.v4.new_code_cell(
    "from pathlib import Path\nROOT = Path(PROJECT_ROOT).resolve()\n"
    "DATA_ROOT = ROOT / 'data'\nARTIFACT_ROOT = ROOT / 'artifacts/models/current'"
)

BOOKS = {
    "00_data_integrity.ipynb": notebook(
        "Dataset integrity and privacy audit",
        [PARAMETERS, nbf.v4.new_code_cell("import hashlib, json, pandas as pd, matplotlib.pyplot as plt\nmanifest = json.loads((DATA_ROOT/'DATASET_MANIFEST.json').read_text())\nentries = manifest['public_datasets'] + manifest['generated_datasets']\nfor item in entries:\n    path = ROOT/item['path']; assert path.stat().st_size == item['bytes']; assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']\npublic = pd.DataFrame(manifest['public_datasets'])\ndisplay(public[['name','bytes']])\nprint('Declared SpamAssassin messages:', sum(item.get('messages',0) for item in manifest['public_datasets']))\nprint('Declared Enron files:', next(item['files'] for item in manifest['public_datasets'] if 'Enron' in item['name']))\npublic.plot.barh(x='name', y='bytes', legend=False, title='Compressed source size'); plt.tight_layout()"), nbf.v4.new_code_cell("daily = pd.read_csv(DATA_ROOT/'synthetic/m365_user_daily.csv.gz')\nprint(daily.shape, daily.isna().sum().sum())\nfig, axes = plt.subplots(1,2,figsize=(11,4)); daily['label'].value_counts().plot.bar(ax=axes[0], title='Synthetic class balance'); daily.isna().mean().nlargest(10).plot.bar(ax=axes[1], title='Largest missingness rates'); plt.tight_layout()"), nbf.v4.new_code_cell("import pyarrow.dataset as ds\nFORBIDDEN = {'subject','body','preview','unique_body','attachment_bytes'}\nprocessed = ds.dataset(DATA_ROOT/'processed/email_metadata_v1', format='parquet', partitioning='hive')\nassert FORBIDDEN.isdisjoint(name.lower() for name in processed.schema.names)\nassert FORBIDDEN.isdisjoint(daily.columns.str.lower())\nprint('Privacy contract verified: forbidden content columns are absent from CSV and Parquet.')")],
    ),
    "01_email_features.ipynb": notebook(
        "Email header feature engineering",
        [PARAMETERS, nbf.v4.new_code_cell("from packages.ml.m365risk_ml.features import load_spamassassin, FEATURE_NAMES, FORBIDDEN_HEADERS\nimport matplotlib.pyplot as plt\nframe = load_spamassassin(DATA_ROOT/'raw/spamassassin')\nprint(frame.shape); display(frame[FEATURE_NAMES].describe().T)\nassert not any(name in frame.columns for name in FORBIDDEN_HEADERS)"), nbf.v4.new_code_cell("frame.groupby('label')[FEATURE_NAMES].mean().T.plot.bar(figsize=(13,5), title='Mean header features by class'); plt.tight_layout()"), nbf.v4.new_code_cell("import seaborn as sns\nsns.heatmap(frame[FEATURE_NAMES + ['label']].corr(), cmap='vlag', center=0); plt.title('Feature correlations')"), nbf.v4.new_code_cell("import pyarrow.dataset as ds\nenron_ds=ds.dataset(DATA_ROOT/'processed/email_metadata_v1',format='parquet',partitioning='hive')\nenron=enron_ds.to_table(filter=ds.field('dataset')=='enron',columns=['sender_hash','recipient_hash','received_at','received_hops']).to_pandas()\nroutes=enron.groupby(['sender_hash','recipient_hash']).size().sort_values(ascending=False); display(routes.head(15).rename('messages'))\nenron.set_index('received_at').resample('D').size().plot(figsize=(12,4),title='Enron normal-routing volume over time'); plt.tight_layout()\nassert set(enron.sender_hash.dropna()).isdisjoint(set(frame.get('message_key', []))), 'identity leakage check'")],
    ),
    "02_model_iterations.ipynb": notebook(
        "Model iterations and calibration",
        [PARAMETERS, nbf.v4.new_code_cell("from packages.ml.m365risk_ml.train import train\nmanifest = train(DATA_ROOT, ARTIFACT_ROOT)\nmanifest['status'], manifest['selected_model']"), nbf.v4.new_code_cell("import json, pandas as pd, matplotlib.pyplot as plt\nmetrics = json.loads((ARTIFACT_ROOT/'metrics.json').read_text())\nmodels = pd.DataFrame(metrics['email_models']); display(models)\nmodels.set_index('name')[['pr_auc','roc_auc','brier','ece']].plot.bar(subplots=True, figsize=(10,9), title='Iteration metrics'); plt.tight_layout()"), nbf.v4.new_code_cell("from sklearn.calibration import calibration_curve\nfrom sklearn.metrics import ConfusionMatrixDisplay, precision_recall_curve\npred = pd.read_parquet(ARTIFACT_ROOT/'evaluation_predictions.parquet'); fig, axes = plt.subplots(1,3,figsize=(16,4))\nfor name in ['rules','logistic','hist_gradient_boosting']:\n    observed, forecast = calibration_curve(pred.label, pred[name], n_bins=10); axes[0].plot(forecast, observed, marker='o', label=name)\naxes[0].plot([0,1],[0,1],'--',color='gray'); axes[0].set_title('Calibration'); axes[0].legend()\nselected = manifest['selected_model']; threshold = metrics['selected']['threshold']; ConfusionMatrixDisplay.from_predictions(pred.label, pred[selected]>=threshold, ax=axes[1], colorbar=False)\np, r, t = precision_recall_curve(pred.label, pred[selected]); axes[2].plot(t,p[:-1],label='precision'); axes[2].plot(t,r[:-1],label='recall'); axes[2].axvline(threshold,color='red',ls='--'); axes[2].set_title('Threshold sensitivity'); axes[2].legend(); plt.tight_layout()"), nbf.v4.new_code_cell("from IPython.display import Image, display\ndisplay(Image(filename=ARTIFACT_ROOT/'model_comparison.png'))")],
    ),
    "03_user_risk_hybrid.ipynb": notebook(
        "User anomaly and hybrid-weight sensitivity",
        [PARAMETERS, nbf.v4.new_code_cell("import pandas as pd, numpy as np, matplotlib.pyplot as plt, seaborn as sns\ndaily = pd.read_csv(DATA_ROOT/'synthetic/m365_user_daily.csv.gz', parse_dates=['date'])\nsample = daily[daily.user_id == daily.user_id.iloc[0]]\nsns.lineplot(data=sample, x='date', y='behaviour_anomaly_score', hue='label'); plt.title('Behavior anomaly timeline')"), nbf.v4.new_code_cell("from sklearn.ensemble import IsolationForest\nbaseline = daily[daily.date < daily.date.quantile(.7)].copy(); values = baseline[['emails_received','external_sender_ratio','sender_domain_novelty']].fillna(0)\nmedian = values.median(); mad = (values-median).abs().median().replace(0,1); baseline['robust_z'] = ((values-median)/mad).abs().max(axis=1)\niso = IsolationForest(contamination=.03,random_state=RANDOM_SEED).fit(values); baseline['isolation_score'] = -iso.score_samples(values)\nfig,axes=plt.subplots(1,2,figsize=(12,4)); sns.histplot(baseline,x='robust_z',hue='label',ax=axes[0]); sns.histplot(baseline,x='isolation_score',hue='label',ax=axes[1]); plt.tight_layout()"), nbf.v4.new_code_cell("from packages.ml.m365risk_ml.scoring import HYBRID_WEIGHTS\nweights = pd.Series(HYBRID_WEIGHTS); weights.plot.bar(title='PDF hybrid weights', color='#4f8cff'); plt.ylim(0, .4)"), nbf.v4.new_code_cell("entra = daily.entra_risk_level.map({'none':0,'low':.3,'medium':.65,'high':1}).fillna(0); posture=(~daily.is_mfa_registered).astype(float); privilege=daily.is_admin.astype(float)\nrows=[]\nfor email_weight in np.linspace(.2,.55,8):\n    remaining=1-email_weight; score=email_weight*daily.email_risk_max + remaining*(.31*daily.behaviour_anomaly_score+.31*entra+.23*posture+.15*privilege)\n    top=score>=score.quantile(.9); rows.append({'email_weight':email_weight,'top_10_recall':(top & daily.label.eq(1)).sum()/daily.label.sum(),'false_alerts_per_100':100*(top & daily.label.eq(0)).mean()})\nsensitivity=pd.DataFrame(rows); sensitivity.plot(x='email_weight',secondary_y='false_alerts_per_100',marker='o',title='Weight sensitivity'); display(sensitivity)"), nbf.v4.new_code_cell("base_score=.35*daily.email_risk_max+.20*daily.behaviour_anomaly_score+.20*entra+.15*posture+.10*privilege\ntop_k=[]\nfor fraction in np.linspace(.01,.25,25):\n    cutoff=base_score.quantile(1-fraction); selected=base_score>=cutoff\n    top_k.append({'review_fraction':fraction,'compromise_recall':(selected & daily.label.eq(1)).sum()/daily.label.sum(),'false_review_rate':(selected & daily.label.eq(0)).sum()/max(1,daily.label.eq(0).sum())})\ntop_k=pd.DataFrame(top_k); top_k.plot(x='review_fraction', y=['compromise_recall','false_review_rate'], marker='o', title='Top-k detection and review trade-off'); plt.axvline(.10,color='red',ls='--'); plt.tight_layout(); display(top_k[top_k.review_fraction.between(.09,.11)])")],
    ),
    "04_export_validation.ipynb": notebook(
        "Explainability, export, and ONNX parity",
        [PARAMETERS, nbf.v4.new_code_cell("import json, pandas as pd\nmanifest = json.loads((ARTIFACT_ROOT/'manifest.json').read_text())\nmetrics = json.loads((ARTIFACT_ROOT/'metrics.json').read_text())\ndisplay(pd.DataFrame([manifest]))\nprint('ONNX max absolute difference:', metrics['onnx_max_abs_difference'])"), nbf.v4.new_code_cell("coefficients = pd.read_csv(ARTIFACT_ROOT/'coefficients.csv').sort_values('coefficient')\ncoefficients.plot.barh(x='feature', y='coefficient', figsize=(9,6), title='Calibrated model coefficients')"), nbf.v4.new_code_cell("import joblib, shap, numpy as np\nfrom packages.ml.m365risk_ml.features import FEATURE_NAMES\npipeline=joblib.load(ARTIFACT_ROOT/'pipeline.joblib'); sample=pd.read_parquet(ARTIFACT_ROOT/'email_features.parquet',columns=FEATURE_NAMES).sample(80,random_state=RANDOM_SEED)\nbackground=sample.iloc[:30]\ndef phishing_probability(values):\n    return pipeline.predict_proba(pd.DataFrame(values,columns=FEATURE_NAMES))[:,1]\nexplainer=shap.Explainer(phishing_probability,background,algorithm='permutation',seed=RANDOM_SEED)\nexplanation=explainer(sample.iloc[30:60],max_evals=2*len(FEATURE_NAMES)+1); explanation.feature_names=FEATURE_NAMES\nshap.plots.beeswarm(explanation,max_display=14)"), nbf.v4.new_code_cell("import hashlib\nfor name, expected in manifest['artifacts'].items():\n    actual = hashlib.sha256((ARTIFACT_ROOT/name).read_bytes()).hexdigest()\n    assert actual == expected, name\nlimit=1e-5 if manifest['selected_model']=='logistic' else 1e-4\nassert metrics['onnx_max_abs_difference'] <= limit\nprint('All artifact checksums and parity gates verified')")],
    ),
}


def main() -> None:
    NOTEBOOKS.mkdir(exist_ok=True)
    for name, book in BOOKS.items():
        nbf.write(book, NOTEBOOKS / name)
        print(f"wrote {NOTEBOOKS / name}")


if __name__ == "__main__":
    main()
