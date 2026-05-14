"""Data analyst agent for chart and insight generation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd


class DataAnalystAgent:
    """Create chart artifacts and useful insights from tabular data."""

    SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls"}

    def __init__(
        self,
        *,
        max_file_mb: int = 50,
        max_rows: int = 200_000,
        max_charts_per_table: int = 3,
    ) -> None:
        """Initialize data analyst limits."""
        self.max_file_mb = max_file_mb
        self.max_rows = max_rows
        self.max_charts_per_table = max_charts_per_table

    def analyze(self, csv_path: str, output_dir: str) -> dict[str, list[str]]:
        """Analyze a CSV, TSV, XLSX, or XLS file and return charts plus insights."""
        input_path = Path(csv_path).expanduser().resolve()
        output_path = Path(output_dir).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        insights: list[str] = []
        charts: list[str] = []
        schema: list[str] = []

        self._validate_input_file(input_path)
        tables = self._load_tables(input_path, warnings=warnings)
        if not tables:
            return {
                "charts": [],
                "insights": [],
                "warnings": ["No readable tables were found in the uploaded file."],
                "schema": [],
            }

        for table_name, raw_df in tables.items():
            if raw_df.empty:
                warnings.append(f"{table_name}: table is empty.")
                continue
            df = self._prepare_dataframe(raw_df)
            table_label = self._display_table_name(input_path, table_name)
            schema.extend(self._schema_summary(table_label, df))
            insights.extend(self._profile_dataframe(table_label, df))
            charts.extend(self._generate_charts(table_label=table_label, df=df, output_dir=output_path))

        if not insights:
            insights.append(f"Loaded {input_path.name}, but no meaningful analytical patterns were detected.")
        return {"charts": charts, "insights": insights, "warnings": warnings, "schema": schema}

    def _validate_input_file(self, input_path: Path) -> None:
        """Validate file existence, extension, and size."""
        if not input_path.exists():
            raise FileNotFoundError(f"Tabular data file not found: {input_path}")
        if not input_path.is_file():
            raise ValueError(f"Expected a file, received: {input_path}")
        if input_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                "Unsupported tabular file type. "
                f"Supported extensions: {sorted(self.SUPPORTED_EXTENSIONS)}. "
                f"Received: {input_path.suffix}"
            )
        file_size_mb = input_path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.max_file_mb:
            raise ValueError(
                f"File is too large for local analysis: {file_size_mb:.1f} MB. "
                f"Limit is {self.max_file_mb} MB."
            )

    def _load_tables(self, input_path: Path, warnings: list[str]) -> dict[str, pd.DataFrame]:
        """Load CSV/TSV/Excel into a mapping of table name to DataFrame."""
        suffix = input_path.suffix.lower()
        if suffix in {".csv", ".tsv"}:
            return {"data": self._read_delimited_file(input_path, suffix=suffix, warnings=warnings)}
        if suffix in {".xlsx", ".xls"}:
            return self._read_excel_file(input_path, warnings=warnings)
        return {}

    def _read_delimited_file(
        self,
        input_path: Path,
        *,
        suffix: str,
        warnings: list[str],
    ) -> pd.DataFrame:
        """Read CSV or TSV with practical fallback encodings."""
        sep = "\t" if suffix == ".tsv" else None
        last_error: Exception | None = None
        for encoding in ("utf-8", "utf-8-sig", "latin1"):
            try:
                return pd.read_csv(
                    input_path,
                    sep=sep,
                    engine="python",
                    encoding=encoding,
                    nrows=self.max_rows,
                )
            except Exception as exc:
                last_error = exc
        raise ValueError(
            f"Could not read delimited file {input_path.name}. "
            f"Last error: {type(last_error).__name__}: {last_error}"
        )

    def _read_excel_file(self, input_path: Path, warnings: list[str]) -> dict[str, pd.DataFrame]:
        """Read all sheets from an Excel workbook."""
        try:
            sheets = pd.read_excel(input_path, sheet_name=None, nrows=self.max_rows)
        except ImportError as exc:
            raise ImportError(
                "Excel analysis requires an Excel engine. Install openpyxl for .xlsx files."
            ) from exc
        except Exception as exc:
            raise ValueError(
                f"Could not read Excel file {input_path.name}: {type(exc).__name__}: {exc}"
            ) from exc
        readable_sheets: dict[str, pd.DataFrame] = {}
        for sheet_name, df in sheets.items():
            if df.empty:
                warnings.append(f"Sheet '{sheet_name}' is empty and was skipped.")
                continue
            readable_sheets[str(sheet_name)] = df
        return readable_sheets

    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean column names and coerce obvious numeric/date columns."""
        prepared = df.copy()
        prepared.columns = self._clean_column_names(prepared.columns)
        prepared = prepared.dropna(axis=0, how="all").dropna(axis=1, how="all")
        for column in prepared.columns:
            series = prepared[column]
            if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
                continue
            converted_numeric = self._try_numeric_conversion(series)
            if converted_numeric is not None:
                prepared[column] = converted_numeric
                continue
            converted_datetime = self._try_datetime_conversion(series)
            if converted_datetime is not None:
                prepared[column] = converted_datetime
        return prepared

    def _clean_column_names(self, columns: Any) -> list[str]:
        """Return stable, human-readable, unique column names."""
        cleaned: list[str] = []
        seen: dict[str, int] = {}
        for idx, column in enumerate(columns, start=1):
            name = str(column).strip()
            if not name or name.lower().startswith("unnamed:"):
                name = f"column_{idx}"
            name = re.sub(r"\s+", " ", name)
            if name in seen:
                seen[name] += 1
                name = f"{name}_{seen[name]}"
            else:
                seen[name] = 1
            cleaned.append(name)
        return cleaned

    def _try_numeric_conversion(self, series: pd.Series) -> pd.Series | None:
        """Convert object series to numeric if most values look numeric."""
        non_null = series.dropna()
        if non_null.empty:
            return None
        as_text = non_null.astype(str).str.strip()
        cleaned = (
            as_text.str.replace(",", "", regex=False)
            .str.replace("₹", "", regex=False)
            .str.replace("$", "", regex=False)
            .str.replace("%", "", regex=False)
            .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        )
        converted = pd.to_numeric(cleaned, errors="coerce")
        if converted.notna().mean() >= 0.75 and converted.notna().sum() >= 3:
            full_cleaned = (
                series.astype(str)
                .str.strip()
                .str.replace(",", "", regex=False)
                .str.replace("₹", "", regex=False)
                .str.replace("$", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
            )
            return pd.to_numeric(full_cleaned, errors="coerce")
        return None

    def _try_datetime_conversion(self, series: pd.Series) -> pd.Series | None:
        """Convert object series to datetime if most values look like dates."""
        non_null = series.dropna()
        if non_null.empty or len(non_null) < 3:
            return None
        converted = pd.to_datetime(non_null, errors="coerce")
        if converted.notna().mean() >= 0.75:
            return pd.to_datetime(series, errors="coerce")
        return None

    def _schema_summary(self, table_label: str, df: pd.DataFrame) -> list[str]:
        """Create schema summary lines for writer context."""
        numeric_cols = self._numeric_columns(df)
        datetime_cols = self._datetime_columns(df)
        categorical_cols = self._categorical_columns(df)
        schema = [f"{table_label}: {len(df):,} rows, {len(df.columns):,} columns."]
        if numeric_cols:
            schema.append(f"{table_label}: numeric columns: {', '.join(numeric_cols[:15])}.")
        if categorical_cols:
            schema.append(f"{table_label}: categorical/text columns: {', '.join(categorical_cols[:15])}.")
        if datetime_cols:
            schema.append(f"{table_label}: date/time columns: {', '.join(datetime_cols[:10])}.")
        return schema

    def _profile_dataframe(self, table_label: str, df: pd.DataFrame) -> list[str]:
        """Generate natural-language data insights."""
        row_count = len(df)
        insights = [f"{table_label}: analyzed {row_count:,} rows and {len(df.columns):,} columns."]
        duplicate_count = int(df.duplicated().sum())
        if duplicate_count:
            insights.append(
                f"{table_label}: found {duplicate_count:,} duplicate rows "
                f"({duplicate_count / max(row_count, 1):.1%} of the dataset)."
            )
        insights.extend(self._missing_value_insights(table_label, df))
        insights.extend(self._numeric_insights(table_label, df))
        insights.extend(self._categorical_insights(table_label, df))
        insights.extend(self._datetime_insights(table_label, df))
        insights.extend(self._correlation_insights(table_label, df))
        insights.extend(self._outlier_insights(table_label, df))
        return insights

    def _missing_value_insights(self, table_label: str, df: pd.DataFrame) -> list[str]:
        """Summarize missing values."""
        missing = df.isna().mean().sort_values(ascending=False)
        missing = missing[missing > 0]
        if missing.empty:
            return [f"{table_label}: no missing values were detected."]
        parts = [f"{column} ({rate:.1%})" for column, rate in missing.head(5).items()]
        return [f"{table_label}: highest missing-value columns: {', '.join(parts)}."]

    def _numeric_insights(self, table_label: str, df: pd.DataFrame) -> list[str]:
        """Summarize numeric columns."""
        insights: list[str] = []
        for column in self._numeric_columns(df)[:6]:
            series = df[column].dropna()
            if series.empty:
                continue
            insights.append(
                f"{table_label}: {column} ranges from {series.min():,.2f} to {series.max():,.2f}; "
                f"mean {series.mean():,.2f}, median {series.median():,.2f}."
            )
        return insights

    def _categorical_insights(self, table_label: str, df: pd.DataFrame) -> list[str]:
        """Summarize categorical columns."""
        insights: list[str] = []
        for column in self._categorical_columns(df)[:5]:
            series = df[column].dropna()
            if series.empty:
                continue
            top_values = series.astype(str).value_counts().head(3)
            if top_values.empty:
                continue
            top_text = ", ".join(f"{value} ({count:,})" for value, count in top_values.items())
            insights.append(
                f"{table_label}: {column} has {series.nunique(dropna=True):,} unique values; "
                f"top values are {top_text}."
            )
        return insights

    def _datetime_insights(self, table_label: str, df: pd.DataFrame) -> list[str]:
        """Summarize date/time columns."""
        insights: list[str] = []
        for column in self._datetime_columns(df)[:4]:
            series = df[column].dropna()
            if not series.empty:
                insights.append(
                    f"{table_label}: {column} spans from {series.min().date()} to {series.max().date()}."
                )
        return insights

    def _correlation_insights(self, table_label: str, df: pd.DataFrame) -> list[str]:
        """Find strongest numeric correlation."""
        numeric_cols = self._numeric_columns(df)
        if len(numeric_cols) < 2:
            return []
        numeric_df = df[numeric_cols].dropna(axis=1, how="all")
        numeric_df = numeric_df.loc[:, numeric_df.nunique(dropna=True) > 1]
        if numeric_df.shape[1] < 2:
            return []
        corr = numeric_df.corr(numeric_only=True).abs()
        best_pair: tuple[str, str] | None = None
        best_value = 0.0
        columns = list(corr.columns)
        for i, left in enumerate(columns):
            for right in columns[i + 1 :]:
                value = corr.loc[left, right]
                if pd.notna(value) and value > best_value:
                    best_value = float(value)
                    best_pair = (left, right)
        if best_pair and best_value >= 0.50:
            return [
                f"{table_label}: strongest numeric relationship is between "
                f"{best_pair[0]} and {best_pair[1]} with correlation {best_value:.2f}."
            ]
        return []

    def _outlier_insights(self, table_label: str, df: pd.DataFrame) -> list[str]:
        """Detect simple IQR-based outliers in numeric columns."""
        insights: list[str] = []
        for column in self._numeric_columns(df)[:6]:
            series = df[column].dropna()
            if len(series) < 10:
                continue
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            outlier_count = int(((series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)).sum())
            if outlier_count:
                insights.append(
                    f"{table_label}: {column} has {outlier_count:,} potential outliers using the 1.5x IQR rule."
                )
        return insights

    def _generate_charts(self, *, table_label: str, df: pd.DataFrame, output_dir: Path) -> list[str]:
        """Generate useful chart artifacts based on detected column types."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except Exception:
            return []
        chart_paths: list[str] = []
        numeric_cols = self._numeric_columns(df)
        categorical_cols = self._categorical_columns(df)
        datetime_cols = self._datetime_columns(df)
        safe_table_name = self._safe_filename(table_label)
        if datetime_cols and numeric_cols and len(chart_paths) < self.max_charts_per_table:
            path = self._make_time_series_chart(
                plt=plt,
                df=df,
                table_name=safe_table_name,
                date_col=datetime_cols[0],
                numeric_col=numeric_cols[0],
                output_dir=output_dir,
            )
            if path:
                chart_paths.append(str(path))
        if categorical_cols and numeric_cols and len(chart_paths) < self.max_charts_per_table:
            path = self._make_category_bar_chart(
                plt=plt,
                df=df,
                table_name=safe_table_name,
                category_col=self._best_category_column(df, categorical_cols),
                numeric_col=numeric_cols[0],
                output_dir=output_dir,
            )
            if path:
                chart_paths.append(str(path))
        if numeric_cols and len(chart_paths) < self.max_charts_per_table:
            path = self._make_histogram(
                plt=plt,
                df=df,
                table_name=safe_table_name,
                numeric_col=numeric_cols[0],
                output_dir=output_dir,
            )
            if path:
                chart_paths.append(str(path))
        if not chart_paths:
            path = self._make_missing_values_chart(
                plt=plt,
                df=df,
                table_name=safe_table_name,
                output_dir=output_dir,
            )
            if path:
                chart_paths.append(str(path))
        return chart_paths

    def _make_time_series_chart(
        self,
        *,
        plt: Any,
        df: pd.DataFrame,
        table_name: str,
        date_col: str,
        numeric_col: str,
        output_dir: Path,
    ) -> Path | None:
        """Create a simple trend chart."""
        work = df[[date_col, numeric_col]].dropna().sort_values(date_col)
        if len(work) < 2:
            return None
        if len(work) > 500:
            work = work.set_index(date_col)[numeric_col].resample("ME").mean().dropna().reset_index()
        path = output_dir / f"{table_name}_{self._safe_filename(numeric_col)}_trend.png"
        plt.figure(figsize=(10, 5))
        plt.plot(work[date_col], work[numeric_col])
        plt.title(f"{numeric_col} over time")
        plt.xlabel(date_col)
        plt.ylabel(numeric_col)
        plt.xticks(rotation=35, ha="right")
        plt.tight_layout()
        plt.savefig(path, dpi=160)
        plt.close()
        return path

    def _make_category_bar_chart(
        self,
        *,
        plt: Any,
        df: pd.DataFrame,
        table_name: str,
        category_col: str,
        numeric_col: str,
        output_dir: Path,
    ) -> Path | None:
        """Create a top-category bar chart."""
        work = df[[category_col, numeric_col]].dropna()
        if work.empty:
            return None
        grouped = work.groupby(category_col, dropna=True)[numeric_col].sum().sort_values(ascending=False).head(10)
        if grouped.empty:
            return None
        path = output_dir / (
            f"{table_name}_{self._safe_filename(category_col)}_by_{self._safe_filename(numeric_col)}.png"
        )
        plt.figure(figsize=(10, 5))
        grouped.plot(kind="bar")
        plt.title(f"Top {category_col} by {numeric_col}")
        plt.xlabel(category_col)
        plt.ylabel(numeric_col)
        plt.xticks(rotation=35, ha="right")
        plt.tight_layout()
        plt.savefig(path, dpi=160)
        plt.close()
        return path

    def _make_histogram(
        self,
        *,
        plt: Any,
        df: pd.DataFrame,
        table_name: str,
        numeric_col: str,
        output_dir: Path,
    ) -> Path | None:
        """Create a numeric distribution chart."""
        series = df[numeric_col].dropna()
        if series.empty:
            return None
        path = output_dir / f"{table_name}_{self._safe_filename(numeric_col)}_distribution.png"
        plt.figure(figsize=(10, 5))
        plt.hist(series, bins=30)
        plt.title(f"Distribution of {numeric_col}")
        plt.xlabel(numeric_col)
        plt.ylabel("Frequency")
        plt.tight_layout()
        plt.savefig(path, dpi=160)
        plt.close()
        return path

    def _make_missing_values_chart(
        self,
        *,
        plt: Any,
        df: pd.DataFrame,
        table_name: str,
        output_dir: Path,
    ) -> Path | None:
        """Create a missing-values chart when no other chart is possible."""
        missing = df.isna().sum()
        missing = missing[missing > 0].sort_values(ascending=False).head(10)
        if missing.empty:
            return None
        path = output_dir / f"{table_name}_missing_values.png"
        plt.figure(figsize=(10, 5))
        missing.plot(kind="bar")
        plt.title("Missing values by column")
        plt.xlabel("Column")
        plt.ylabel("Missing values")
        plt.xticks(rotation=35, ha="right")
        plt.tight_layout()
        plt.savefig(path, dpi=160)
        plt.close()
        return path

    def _numeric_columns(self, df: pd.DataFrame) -> list[str]:
        """Return numeric columns excluding booleans."""
        return [
            column
            for column in df.columns
            if pd.api.types.is_numeric_dtype(df[column]) and not pd.api.types.is_bool_dtype(df[column])
        ]

    def _datetime_columns(self, df: pd.DataFrame) -> list[str]:
        """Return datetime columns."""
        return [column for column in df.columns if pd.api.types.is_datetime64_any_dtype(df[column])]

    def _categorical_columns(self, df: pd.DataFrame) -> list[str]:
        """Return text/categorical columns."""
        categorical: list[str] = []
        for column in df.columns:
            series = df[column]
            if pd.api.types.is_datetime64_any_dtype(series):
                continue
            if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
                continue
            categorical.append(column)
        return categorical

    def _best_category_column(self, df: pd.DataFrame, categorical_cols: list[str]) -> str:
        """Choose a category column suitable for a bar chart."""
        best_col = categorical_cols[0]
        best_score = -1
        for column in categorical_cols:
            unique_count = df[column].nunique(dropna=True)
            if 2 <= unique_count <= 20:
                score = 100 - unique_count
            elif 21 <= unique_count <= 50:
                score = 50 - unique_count
            else:
                score = -unique_count
            if score > best_score:
                best_score = score
                best_col = column
        return best_col

    def _display_table_name(self, input_path: Path, table_name: str) -> str:
        """Return a readable table label."""
        if table_name == "data":
            return input_path.stem
        return f"{input_path.stem} / {table_name}"

    def _safe_filename(self, value: str) -> str:
        """Convert arbitrary labels into safe filenames."""
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip()).strip("_")
        return cleaned[:80] or "table"
