# Démonstration technique — moteur de risque M365

Cette démonstration fonctionne **sans accès à une entreprise**. Elle utilise Mock Graph et des données générées. Elle prouve le chemin logiciel, pas la précision d'un modèle sur des attaques réelles ni une intégration Entra ID validée.

## 1. Vérifier les services

Depuis la racine du projet :

```bash
./scripts/doctor.sh --after-start
```

Montrer que l'API, le worker, Mock Graph et les interfaces répondent. Si le stack n'est pas démarré, suivre `./scripts/install.sh --check` puis `./scripts/install.sh`. L'installation fraîche a besoin de Docker Hub et d'un réseau fonctionnel.

## 2. Lancer la collecte et le feature engineering

Choisir un **nouveau** nom de sortie à chaque essai :

```bash
python3 scripts/scan_cli.py scan --demo --out output/scans/reunion-001
python3 scripts/scan_cli.py results --demo --top 5
```

Expliquer le chemin : commande → API REST → job worker → Mock Graph → métadonnées autorisées → fenêtres de features V2 → score opérationnel et export administrateur. Montrer la distribution des risques renvoyée par `results`, puis `output/scans/reunion-001/manifest.json` et une ligne de `feature_windows.jsonl`. L'export comprend les composantes, leur disponibilité et des identifiants pseudonymisés. Il n'inclut ni corps/sujet d'email, ni score existant, ni label d'incident. Les scores opérationnels proviennent du modèle runtime déjà configuré, **pas** du modèle expérimental entraîné à l'étape 3.

Pour séparer les deux actions : `scan --demo --scan-only` lance la collecte sans export, et `collect --demo --out output/scans/reunion-002` exporte les fenêtres déjà stockées.

## 3. Montrer l'entraînement séparé de la machine cliente

Le scanner ne sait pas si un utilisateur est réellement compromis. L'entraînement supervisé exige donc un fichier de labels `sample_id,label` établi indépendamment. Pour la réunion, générer uniquement un jeu synthétique clairement marqué :

```bash
python3 scripts/generate_remote_training_demo.py --out output/scans/training-demo-001
.venv/bin/python scripts/train_scanned.py \
  --features output/scans/training-demo-001/feature_windows.jsonl \
  --labels output/scans/training-demo-001/generated_labels.csv \
  --out output/training/training-demo-001 \
  --public-notebook
```

Montrer `output/training/training-demo-001/report.json` : algorithme sélectionné, précision, rappel, PR-AUC, séparation des utilisateurs entre entraînement/validation/test, versions des dépendances et statut `experimental_unapproved`. Le fichier `model.joblib` est un artefact expérimental **non branché à l'inférence de l'API**. Les chiffres synthétiques ne démontrent pas la performance sur une entreprise.

Le même script peut tourner sur un serveur distant. Une machine cliente ne doit pas entraîner de modèle : elle collecte, construit les features et utilise seulement un modèle préalablement validé. Un notebook public ne reçoit que des données générées ; des données réelles exigent un environnement de calcul contrôlé ou approuvé par l'entreprise.

## 4. Réponse aux questions de déploiement

| Question | Réponse exacte aujourd'hui |
| --- | --- |
| L'API scanne-t-elle déjà un vrai tenant Entra ID ? | Un adaptateur Graph et un flux de consentement existent, mais l'installation entreprise et le scan réel ne sont pas validés. L'installeur public démarre uniquement le mode Mock Graph. |
| Les emails privés sont-ils lus ? | Le projet vise uniquement les métadonnées et en-têtes nécessaires ; aucun corps ou sujet n'est exporté pour l'entraînement. Les permissions réelles devront être revues avant déploiement. |
| Le modèle est-il universel et validé ? | Non. Le test synthétique vérifie le pipeline. Il faut des labels indépendants, une évaluation multi-tenant et temporelle, puis une approbation avant distribution. |
| Faut-il un GPU chez chaque client ? | Non. L'entraînement doit être séparé ; l'inférence de ces modèles tabulaires fonctionne sur CPU. |
| Peut-on publier le code sur GitHub ? | Oui, sans tokens, exports, données d'entreprise ni modèles privés. GitHub distribue le code, pas un service hébergé. |

## Suite après la réunion

Obtenir un tenant de test autorisé et vérifier les permissions Graph, le volume réellement disponible, le traitement des données manquantes et l'isolation multi-tenant. Constituer un corpus labellisé de manière indépendante, tester sur des périodes et organisations distinctes, puis construire un processus de validation/promotion et de retour arrière pour chaque nouvelle version du modèle.
