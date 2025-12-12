# Odoo Generative BI

**Connectez votre Odoo à Google Cloud Platform pour une Intelligence Artificielle Générative.**

Ce module permet de synchroniser vos données Odoo vers BigQuery pour l'analyse de données et d'utiliser Vertex AI (Gemini) pour poser des questions en langage naturel sur vos données.

## Fonctionnalités Clés

- **Synchronisation BigQuery (BYOK)** : Exportez vos modèles Odoo vers Google BigQuery pour des analyses avancées.
- **IA Générative (Text-to-SQL)** : Utilisez Gemini (via Vertex AI) pour transformer vos questions en requêtes SQL et analyser vos données sans connaitre le SQL.
- **Tableau de Bord Intégré** : Visualisez les résultats directement dans Odoo avec un tableau de bord interactif (Chart.js).

## Prérequis

### Côté Odoo
- Odoo 17.0+ (Compatible 18.0 et 19.0 master)
- Bibliothèques Python requises :
  ```bash
  pip install google-cloud-bigquery google-cloud-aiplatform pandas db-dtypes
  ```

### Côté Google Cloud Platform (GCP)
1. **Projet GCP** : Créez un nouveau projet ou utilisez-en un existant.
2. **APIs** : Activez les APIs suivantes :
   - BigQuery API
   - Vertex AI API
3. **Compte de Service (Service Account)** : Créez un compte de service et attribuez-lui les rôles suivants :
   - `BigQuery Admin` (ou a minima `BigQuery Data Editor` + `BigQuery Job User`)
   - `Vertex AI User`
4. **Clé JSON** : Générez et téléchargez la clé JSON pour ce compte de service.

## Installation

1. Placez ce dossier (`odoo_gen_bi`) dans votre répertoire `custom-addons`.
2. Assurez-vous que les dépendances Python sont installées sur votre serveur Odoo.
3. Mettez à jour la liste des applications dans Odoo.
4. Recherchez **Odoo Generative BI** et cliquez sur **Installer**.

## Configuration

Une fois installé, allez dans **Paramètres > Odoo Generative BI** (section tout en bas ou via la recherche).

1. **GCP Service Account JSON** : Chargez le fichier JSON téléchargé précédemment.
   - Le champ **GCP Project ID** se remplira automatiquement.
2. **BigQuery Dataset ID** : Définissez le nom du dataset (par défaut `odoo_bi`). Le module créera ce dataset automatiquement s'il n'existe pas.
3. **GCP Location** : Choisissez la région de vos ressources (ex: `us-central1` ou `europe-westX`). **Important** : Le dataset BigQuery et l'emplacement Vertex AI doivent être compatibles.
4. **AI Model Name** : Sélectionnez le modèle Gemini à utiliser (ex: `gemini-1.5-flash` pour la rapidité, ou `gemini-1.5-pro` pour des requêtes complexes).
5. **Paramètres de Synchronisation** : Configurez la fréquence de la tâche planifiée (CRON) pour synchroniser automatiquement vos données vers BigQuery.

## Utilisation

### 1. Synchronisation des Données
Avant de poser des questions, vos données doivent être dans BigQuery.
- Vous pouvez lancer une synchronisation manuelle depuis les paramètres ou attendre le CRON.
- Le module synchronise les modèles définis dans le code (ex: `sale.order`, `account.move`, etc.).

### 2. Dashboard BI
Accédez au menu principal **Generative BI**.
1. **Posez votre question** dans la barre de recherche (ex: *"Montre-moi les top 5 clients par chiffre d'affaires cette année"*).
2. Cliquez sur **Générer SQL**. L'IA va traduire votre question en requête SQL compatible BigQuery.
3. Vérifiez la requête (optionnel) et cliquez sur **Exécuter**.
4. Les résultats s'affichent sous forme de tableau et de graphique.

## Structure du Module

- `models/bi_etl.py` : Logique d'export et synchronisation vers BigQuery (Extract-Load).
- `models/bi_ai.py` : Intégration avec Vertex AI pour la génération de SQL.
- `static/src/` : Composants Javascript (OWL) pour le tableau de bord frontend.

