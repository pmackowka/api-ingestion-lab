# Konfiguracja od zera

Jednorazowe kroki dla kogoś, kto kopiuje projekt. Kroki specyficzne dla źródła są w „Konfiguracji” README jego folderu.

## Wspólne środowisko

Foldery są niezależne od siebie, ale dzielą jedno środowisko Pythona (`pyproject.toml`) i jedną tożsamość w GCP: konto usługi `ingest-runner`, pod które podszywasz się lokalnie (impersonation) — bez pliku z kluczem. Wymagane: [uv](https://docs.astral.sh/uv/) i [gcloud CLI](https://cloud.google.com/sdk/docs/install). Konfiguracja jednorazowa, od zera:

```bash
# Zmienne: ID projektu GCP jest globalnie unikalne — wymyśl własne. E-mail = Twoje konto Google.
PROJECT=api-ingestion-lab-bq
ME=twoj-email@gmail.com
SA=ingest-runner@$PROJECT.iam.gserviceaccount.com

# 1. Zależności Pythona do .venv/ (wersje z uv.lock).
uv sync

# 2. Logowanie gcloud (komendy administracyjne niżej) i projekt domyślny.
gcloud auth login
gcloud projects create $PROJECT            # pomiń, jeśli projekt już istnieje; billing niepotrzebny (sandbox BigQuery)
gcloud config set project $PROJECT

# 3. API BigQuery — w nowym projekcie wszystkie API są wyłączone.
gcloud services enable bigquery.googleapis.com --project=$PROJECT

# 4. Konto usługi: osobna tożsamość dla skryptów, ta sama lokalnie i w harmonogramie (GitHub Actions + WIF).
gcloud iam service-accounts create ingest-runner --project=$PROJECT --display-name="Ingest runner (GA4, BigQuery)"

# 5. Najmniejsze potrzebne uprawnienia w BigQuery: tworzenie tabel i zapis (dataEditor), uruchamianie zadań (jobUser),
#    odczyt przez Storage Read API, którego wymaga dbt v2 (readSessionUser).
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/bigquery.dataEditor --condition=None
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/bigquery.jobUser --condition=None
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/bigquery.readSessionUser --condition=None

# 6. Twoje konto może generować krótkotrwałe tokeny konta usługi — zamiast pliku z kluczem, który mógłby wyciec.
gcloud iam service-accounts add-iam-policy-binding $SA --project=$PROJECT --member=user:$ME --role=roles/iam.serviceAccountTokenCreator

# 7. ADC = poświadczenia, które biblioteki Google biorą automatycznie. Od teraz każdy skrypt działa jako konto usługi.
#    Zakresy: cloud-platform (BigQuery), analytics.readonly (etap 3, GA4), webmasters.readonly (etap 4, Search Console).
#    Nowy zakres = to samo logowanie jeszcze raz z pełną listą.
gcloud auth application-default login --impersonate-service-account=$SA \
  --scopes="https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/webmasters.readonly"

# 8. Kontrola: zwraca token = ADC działa.
gcloud auth application-default print-access-token > /dev/null && echo "ADC OK"
```

Datasety powstają same przy pierwszym uruchomieniu, w lokalizacji `EU` (`LOCATION` w [`common/bigquery.py`](../common/bigquery.py)). Lokalizacji datasetu nie da się zmienić po utworzeniu — jeśli istnieje w innej, skrypt przerwie z błędem.

Dalej: sekcja „Konfiguracja” w README konkretnego folderu (kroki specyficzne dla źródła).

## GitHub Actions

Workflow [`.github/workflows/pipeline.yml`](../.github/workflows/pipeline.yml) codziennie o 1:41 czasu polskiego uruchamia każde źródło z `--lookback-days 7` jako osobny job macierzy — awaria jednego nie zatrzymuje pozostałych. Porównanie wariantów: [orkiestracja.md](orkiestracja.md).

Konfiguracja (raz, po [„Wspólnym środowisku”](#wspólne-środowisko)):

```bash
PROJECT=api-ingestion-lab-bq
REPO=<właściciel>/<repo>                 # repo na GitHubie, np. pmackowka/api-ingestion-lab
SA=ingest-runner@$PROJECT.iam.gserviceaccount.com
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format="value(projectNumber)")   # ścieżki WIF wymagają numeru, nie ID

# 1. API do wymiany tokenów (STS) i wystawiania tokenów konta usługi.
gcloud services enable sts.googleapis.com iamcredentials.googleapis.com --project=$PROJECT

# 2. Pula Workload Identity: miejsce w GCP na tożsamości spoza Google (tu: GitHub).
gcloud iam workload-identity-pools create github --project=$PROJECT --location=global --display-name="GitHub Actions Pool"

# 3. Dostawca OIDC: ufa tokenom GitHuba, mapuje ich pola na atrybuty i wpuszcza tylko jedno repo.
gcloud iam workload-identity-pools providers create-oidc api-ingestion-lab --project=$PROJECT --location=global \
  --workload-identity-pool=github --display-name="GitHub api-ingestion-lab" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository == '$REPO'"

# 4. Repo może działać jako konto usługi — z jego dostępem do BigQuery, GA4 i Search Console.
gcloud iam service-accounts add-iam-policy-binding $SA --project=$PROJECT --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"

# 5. Wartość do pola workload_identity_provider w pipeline.yml.
gcloud iam workload-identity-pools providers describe api-ingestion-lab --project=$PROJECT --location=global --workload-identity-pool=github --format="value(name)"

# 6. Ręczny przebieg testowy i podgląd na żywo.
gh workflow run pipeline.yml && gh run watch
```

Źródło komend: [google-github-actions/auth — WIF przez konto usługi](https://github.com/google-github-actions/auth#indirect-wif) (sprawdzone 2026-11-18). Wariant przez konto usługi, a nie bezpośredni, bo GA4 i Search Console nadają dostęp po adresie e-mail, a ten ma tylko konto usługi.
