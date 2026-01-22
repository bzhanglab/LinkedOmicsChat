"""
CPTAC Data Service
Handles access to CPTAC (Clinical Proteomic Tumor Analysis Consortium) datasets
"""
from typing import Dict, Any, Optional, List
import pandas as pd
import numpy as np
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# CPTAC cancer types and datasets
CPTAC_DATASETS = {
    "BRCA": {
        "name": "CPTAC Breast Cancer",
        "cancer_type": "Breast invasive carcinoma",
        "sample_count": 122,
        "data_types": ["proteomics", "rna_seq", "clinical", "phosphoproteomics"],
        "publication": "Nature 2016"
    },
    "LUAD": {
        "name": "CPTAC Lung Adenocarcinoma",
        "cancer_type": "Lung adenocarcinoma",
        "sample_count": 110,
        "data_types": ["proteomics", "rna_seq", "clinical"],
        "publication": "Cell 2020"
    },
    "COAD": {
        "name": "CPTAC Colon Cancer",
        "cancer_type": "Colon adenocarcinoma",
        "sample_count": 100,
        "data_types": ["proteomics", "rna_seq", "clinical"],
        "publication": "Cell 2019"
    },
    "OV": {
        "name": "CPTAC Ovarian Cancer",
        "cancer_type": "Ovarian serous cystadenocarcinoma",
        "sample_count": 174,
        "data_types": ["proteomics", "rna_seq", "clinical", "phosphoproteomics"],
        "publication": "Cell 2016"
    },
    "GBM": {
        "name": "CPTAC Glioblastoma",
        "cancer_type": "Glioblastoma multiforme",
        "sample_count": 99,
        "data_types": ["proteomics", "rna_seq", "clinical"],
        "publication": "Cell 2021"
    },
    "PDAC": {
        "name": "CPTAC Pancreatic Cancer",
        "cancer_type": "Pancreatic adenocarcinoma",
        "sample_count": 140,
        "data_types": ["proteomics", "rna_seq", "clinical"],
        "publication": "Cell 2021"
    }
}


class CPTACService:
    """Service for accessing CPTAC data"""

    def __init__(self, data_dir: Optional[str] = None):
        """
        Initialize CPTAC service

        Args:
            data_dir: Directory to store cached CPTAC data
        """
        if data_dir is None:
            # Default to backend/data/cptac
            self.data_dir = Path(__file__).parent.parent.parent / "data" / "cptac"
        else:
            self.data_dir = Path(data_dir)

        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"CPTAC service initialized with data directory: {self.data_dir}"
        )

    def list_available_datasets(self) -> List[Dict[str, str]]:
        """List all available CPTAC datasets"""
        return [
            {
                "code": code,
                "name": info["name"],
                "cancer_type": info["cancer_type"],
                "sample_count": info["sample_count"],
                "data_types": info["data_types"]
            }
            for code, info in CPTAC_DATASETS.items()
        ]

    def get_dataset_info(self, cancer_type: str) -> Optional[Dict[str, Any]]:
        """Get information about a CPTAC dataset"""
        return CPTAC_DATASETS.get(cancer_type.upper())

    async def get_proteomics_data(
        self,
        cancer_type: str,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Get protein expression data for a cancer type

        Args:
            cancer_type: CPTAC cancer type code (e.g., "BRCA")
            use_cache: Whether to use cached data if available

        Returns:
            DataFrame with proteins as rows, samples as columns
        """
        cancer_type = cancer_type.upper()

        # Check cache first
        cache_file = (
            self.data_dir / cancer_type / "proteomics_expression.parquet"
        )

        if use_cache and cache_file.exists():
            logger.info(
                f"Loading cached proteomics data for {cancer_type} "
                f"from {cache_file}"
            )
            try:
                cached_data = pd.read_parquet(cache_file)
                # Basic validation: check if data looks valid
                if len(cached_data) == 0 or len(cached_data.columns) == 0:
                    logger.warning(
                        f"Cached data for {cancer_type} is empty, regenerating..."
                    )
                    cache_file.unlink()
                    return await self.get_proteomics_data(cancer_type, use_cache=False)
                
                logger.info(
                    f"✅ Cached data loaded: {len(cached_data)} proteins, "
                    f"{len(cached_data.columns)} samples"
                )
                return cached_data
            except Exception as e:
                logger.warning(
                    f"Error loading cache, will generate mock data: {e}"
                )

        # For now, generate mock data
        # In production, this would download from CPTAC Data Portal
        logger.info(
            f"Generating mock proteomics data for {cancer_type} "
            f"(real data download not yet implemented)"
        )

        proteomics_data = self._generate_mock_proteomics_data(cancer_type)

        # Cache the data
        if use_cache:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                proteomics_data.to_parquet(cache_file)
                logger.info(f"Cached proteomics data to {cache_file}")
            except Exception as e:
                logger.warning(f"Could not cache data: {e}")

        return proteomics_data

    async def get_expression_data(
        self,
        cancer_type: str,
        data_type: str = "RNA-seq",
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Get gene expression data for a cancer type (CPTAC also has RNA-seq)

        Args:
            cancer_type: CPTAC cancer type code
            data_type: "RNA-seq" or "proteomics"
            use_cache: Whether to use cached data

        Returns:
            DataFrame with genes/proteins as rows, samples as columns
        """
        if data_type.lower() in ["proteomics", "protein"]:
            return await self.get_proteomics_data(cancer_type, use_cache)
        else:
            # For RNA-seq, use similar structure to TCGA
            return await self._get_rnaseq_data(cancer_type, use_cache)

    async def _get_rnaseq_data(
        self,
        cancer_type: str,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """Get RNA-seq data (CPTAC also has transcriptomics)"""
        cancer_type = cancer_type.upper()
        cache_file = (
            self.data_dir / cancer_type / "rna_seq_expression.parquet"
        )

        if use_cache and cache_file.exists():
            try:
                return pd.read_parquet(cache_file)
            except Exception as e:
                logger.warning(f"Error loading RNA-seq cache: {e}")

        # Generate mock RNA-seq data
        dataset_info = self.get_dataset_info(cancer_type)
        n_samples = dataset_info["sample_count"] if dataset_info else 100

        return self._generate_mock_rnaseq_data(cancer_type, n_samples)

    def _generate_mock_proteomics_data(
        self,
        cancer_type: str,
        n_proteins: int = 12000,
        n_samples: int = None
    ) -> pd.DataFrame:
        """
        Generate mock proteomics data for testing

        Args:
            cancer_type: CPTAC cancer type code
            n_proteins: Number of proteins to simulate
            n_samples: Number of samples (default from dataset info)

        Returns:
            DataFrame with mock proteomics data
        """
        dataset_info = self.get_dataset_info(cancer_type)
        if n_samples is None:
            n_samples = (
                dataset_info["sample_count"] if dataset_info else 100
            )

        # Use real gene/protein names instead of fake IDs
        # Comprehensive list of real human gene symbols (commonly studied in cancer)
        real_gene_names = [
            "TP53", "BRCA1", "BRCA2", "EGFR", "KRAS", "PIK3CA", "PTEN",
            "AKT1", "ERBB2", "MYC", "CDKN2A", "RB1", "MDM2", "VEGFA",
            "TGFB1", "IL6", "TNF", "IFNG", "CD4", "CD8A", "FOXP3",
            "PDCD1", "CTLA4", "PDL1", "BRAF", "NRAS", "HRAS", "MET",
            "FGFR1", "FGFR2", "FGFR3", "KIT", "PDGFRA", "RET", "ALK",
            "ROS1", "NTRK1", "NTRK2", "NTRK3", "ERBB3", "ERBB4", "IGF1R",
            "INSR", "JAK1", "JAK2", "JAK3", "STAT3", "STAT5A", "STAT5B",
            "PIK3CB", "PIK3CD", "PIK3CG", "PIK3R1", "PIK3R2", "MTOR",
            "RICTOR", "RPTOR", "AKT2", "AKT3", "GSK3B", "CDK4", "CDK6",
            "CCND1", "CCNE1", "CCNE2", "CDK2", "CDK1", "PLK1", "AURKA",
            "AURKB", "BUB1", "BUB1B", "MAD2L1", "CDC20", "ANAPC1",
            "APC", "CTNNB1", "GSK3A", "AXIN1", "AXIN2", "TCF7", "LEF1",
            "MYCN", "MYCL", "MAX", "MXD1", "MXI1", "MGA", "MNT",
            "E2F1", "E2F2", "E2F3", "E2F4", "E2F5", "E2F6", "E2F7",
            "E2F8", "RB1", "RBL1", "RBL2", "CDKN1A", "CDKN1B", "CDKN1C",
            "CDKN2B", "CDKN2C", "CDKN2D", "ARF", "MDM4", "CHEK1", "CHEK2",
            "ATM", "ATR", "RAD51", "RAD52", "BRCA1", "BRCA2", "PALB2",
            "BRIP1", "BARD1", "RAD50", "MRE11", "NBN", "FANCA", "FANCB",
            "FANCC", "FANCD2", "FANCE", "FANCF", "FANCG", "FANCI", "FANCL",
            "FANCM", "XRCC1", "XRCC2", "XRCC3", "XRCC4", "XRCC5", "XRCC6",
            "LIG1", "LIG3", "LIG4", "PARP1", "PARP2", "PARP3", "PARP4",
            "PARP5A", "PARP5B", "PARP6", "PARP7", "PARP8", "PARP9", "PARP10",
            "PARP11", "PARP12", "PARP13", "PARP14", "PARP15", "PARP16",
            "TERT", "TERC", "DKC1", "TINF2", "RTEL1", "POT1", "TPP1",
            "RAP1", "TRF1", "TRF2", "TANK1", "TANK2", "PINX1", "POT1",
            "OBFC1", "CTC1", "STN1", "TEN1", "WRAP53", "SMG1", "SMG5",
            "SMG6", "SMG7", "UPF1", "UPF2", "UPF3A", "UPF3B", "RENT1",
            "RENT2", "RENT3", "EIF4A1", "EIF4A2", "EIF4A3", "EIF4E",
            "EIF4E2", "EIF4E3", "EIF4G1", "EIF4G2", "EIF4G3", "EIF4B",
            "EIF4H", "EIF3A", "EIF3B", "EIF3C", "EIF3D", "EIF3E", "EIF3F",
            "EIF3G", "EIF3H", "EIF3I", "EIF3J", "EIF3K", "EIF3L", "EIF3M"
        ]
        
        # Randomly select gene names (with replacement if needed)
        import random
        random.seed(42)  # For reproducibility
        
        # Ensure we have some common cancer genes at the start
        essential_genes = ["TP53", "BRCA1", "BRCA2", "EGFR", "KRAS", "PIK3CA", "PTEN"]
        
        # Start with essential genes, then add random ones (allowing duplicates)
        protein_names = essential_genes.copy()
        remaining = n_proteins - len(essential_genes)
        if remaining > 0:
            protein_names.extend(random.choices(real_gene_names, k=remaining))

        # Generate sample IDs (CPTAC format)
        sample_ids = [
            f"CPTAC-{cancer_type}-{i:03d}" for i in range(1, n_samples + 1)
        ]

        # Generate protein expression values (log-normal, typical for proteomics)
        np.random.seed(42)
        log_mean = 4.0  # Slightly lower than RNA-seq
        log_std = 1.8
        expression_values = np.random.lognormal(
            mean=log_mean,
            sigma=log_std,
            size=(n_proteins, n_samples)
        )

        # Create DataFrame
        proteomics_df = pd.DataFrame(
            expression_values,
            index=protein_names,
            columns=sample_ids
        )

        logger.info(
            f"Generated mock proteomics data: {n_proteins} proteins, "
            f"{n_samples} samples"
        )

        return proteomics_df

    def _generate_mock_rnaseq_data(
        self,
        cancer_type: str,
        n_samples: int
    ) -> pd.DataFrame:
        """Generate mock RNA-seq data (similar to TCGA)"""
        n_genes = 20000
        
        # Use real gene names (same list as proteomics)
        real_gene_names = [
            "TP53", "BRCA1", "BRCA2", "EGFR", "KRAS", "PIK3CA", "PTEN",
            "AKT1", "ERBB2", "MYC", "CDKN2A", "RB1", "MDM2", "VEGFA",
            "TGFB1", "IL6", "TNF", "IFNG", "CD4", "CD8A", "FOXP3",
            "PDCD1", "CTLA4", "PDL1", "BRAF", "NRAS", "HRAS", "MET",
            "FGFR1", "FGFR2", "FGFR3", "KIT", "PDGFRA", "RET", "ALK",
            "ROS1", "NTRK1", "NTRK2", "NTRK3", "ERBB3", "ERBB4", "IGF1R",
            "INSR", "JAK1", "JAK2", "JAK3", "STAT3", "STAT5A", "STAT5B",
            "PIK3CB", "PIK3CD", "PIK3CG", "PIK3R1", "PIK3R2", "MTOR",
            "RICTOR", "RPTOR", "AKT2", "AKT3", "GSK3B", "CDK4", "CDK6",
            "CCND1", "CCNE1", "CCNE2", "CDK2", "CDK1", "PLK1", "AURKA",
            "AURKB", "BUB1", "BUB1B", "MAD2L1", "CDC20", "ANAPC1",
            "APC", "CTNNB1", "GSK3A", "AXIN1", "AXIN2", "TCF7", "LEF1",
            "MYCN", "MYCL", "MAX", "MXD1", "MXI1", "MGA", "MNT",
            "E2F1", "E2F2", "E2F3", "E2F4", "E2F5", "E2F6", "E2F7",
            "E2F8", "RB1", "RBL1", "RBL2", "CDKN1A", "CDKN1B", "CDKN1C",
            "CDKN2B", "CDKN2C", "CDKN2D", "ARF", "MDM4", "CHEK1", "CHEK2",
            "ATM", "ATR", "RAD51", "RAD52", "PALB2", "BRIP1", "BARD1",
            "RAD50", "MRE11", "NBN", "FANCA", "FANCB", "FANCC", "FANCD2",
            "FANCE", "FANCF", "FANCG", "FANCI", "FANCL", "FANCM", "XRCC1",
            "XRCC2", "XRCC3", "XRCC4", "XRCC5", "XRCC6", "LIG1", "LIG3",
            "LIG4", "PARP1", "PARP2", "PARP3", "PARP4", "PARP5A", "PARP5B",
            "PARP6", "PARP7", "PARP8", "PARP9", "PARP10", "PARP11", "PARP12",
            "PARP13", "PARP14", "PARP15", "PARP16", "TERT", "TERC", "DKC1",
            "TINF2", "RTEL1", "POT1", "TPP1", "RAP1", "TRF1", "TRF2",
            "TANK1", "TANK2", "PINX1", "OBFC1", "CTC1", "STN1", "TEN1",
            "WRAP53", "SMG1", "SMG5", "SMG6", "SMG7", "UPF1", "UPF2",
            "UPF3A", "UPF3B", "RENT1", "RENT2", "RENT3", "EIF4A1", "EIF4A2",
            "EIF4A3", "EIF4E", "EIF4E2", "EIF4E3", "EIF4G1", "EIF4G2",
            "EIF4G3", "EIF4B", "EIF4H", "EIF3A", "EIF3B", "EIF3C", "EIF3D",
            "EIF3E", "EIF3F", "EIF3G", "EIF3H", "EIF3I", "EIF3J", "EIF3K",
            "EIF3L", "EIF3M", "MAPK1", "MAPK3", "MAPK8", "MAPK9", "MAPK10",
            "MAPK11", "MAPK12", "MAPK13", "MAPK14", "MAP2K1", "MAP2K2",
            "MAP2K3", "MAP2K4", "MAP2K5", "MAP2K6", "MAP2K7", "MAP3K1",
            "MAP3K2", "MAP3K3", "MAP3K4", "MAP3K5", "MAP3K6", "MAP3K7",
            "MAP3K8", "MAP3K9", "MAP3K10", "MAP3K11", "MAP3K12", "MAP3K13",
            "MAP3K14", "MAP3K15", "RAF1", "ARAF", "BRAF", "HRAS", "KRAS",
            "NRAS", "RRAS", "RRAS2", "MRAS", "RAP1A", "RAP1B", "RAP2A",
            "RAP2B", "RAP2C", "RAB1A", "RAB1B", "RAB2A", "RAB2B", "RAB3A",
            "RAB3B", "RAB3C", "RAB3D", "RAB4A", "RAB4B", "RAB5A", "RAB5B",
            "RAB5C", "RAB6A", "RAB6B", "RAB7A", "RAB7B", "RAB8A", "RAB8B",
            "RAB9A", "RAB9B", "RAB10", "RAB11A", "RAB11B", "RAB12", "RAB13",
            "RAB14", "RAB15", "RAB18", "RAB19", "RAB20", "RAB21", "RAB22A",
            "RAB23", "RAB24", "RAB25", "RAB26", "RAB27A", "RAB27B", "RAB28",
            "RAB30", "RAB31", "RAB32", "RAB33A", "RAB33B", "RAB34", "RAB35",
            "RAB36", "RAB37", "RAB38", "RAB39A", "RAB39B", "RAB40A", "RAB40B",
            "RAB40C", "RAB41", "RAB42", "RAB43", "RAB44", "RAB45", "RABL2A",
            "RABL2B", "RABL3", "RABL4", "RABL5", "RABL6"
        ]
        
        # Randomly select gene names (with replacement if needed)
        import random
        random.seed(42)  # For reproducibility
        
        # Ensure we have some common cancer genes at the start
        essential_genes = ["TP53", "BRCA1", "BRCA2", "EGFR", "KRAS", "PIK3CA", "PTEN"]
        
        # Start with essential genes, then add random ones (allowing duplicates)
        gene_names = essential_genes.copy()
        remaining = n_genes - len(essential_genes)
        if remaining > 0:
            gene_names.extend(random.choices(real_gene_names, k=remaining))

        sample_ids = [
            f"CPTAC-{cancer_type}-{i:03d}" for i in range(1, n_samples + 1)
        ]

        np.random.seed(42)
        expression_values = np.random.lognormal(
            mean=5.0,
            sigma=2.0,
            size=(n_genes, n_samples)
        )

        return pd.DataFrame(
            expression_values,
            index=gene_names,
            columns=sample_ids
        )

    async def get_clinical_data(
        self,
        cancer_type: str,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """Get clinical data for a cancer type"""
        cancer_type = cancer_type.upper()
        cache_file = self.data_dir / cancer_type / "clinical_data.parquet"

        if use_cache and cache_file.exists():
            try:
                return pd.read_parquet(cache_file)
            except Exception as e:
                logger.warning(f"Error loading clinical cache: {e}")

        # Generate mock clinical data
        dataset_info = self.get_dataset_info(cancer_type)
        n_samples = (
            dataset_info["sample_count"] if dataset_info else 100
        )

        np.random.seed(42)
        sample_ids = [
            f"CPTAC-{cancer_type}-{i:03d}"
            for i in range(1, n_samples + 1)
        ]

        clinical_data = pd.DataFrame({
            "sample_id": sample_ids,
            "age": np.random.randint(30, 85, n_samples),
            "gender": np.random.choice(["Male", "Female"], n_samples),
            "stage": np.random.choice(
                ["Stage I", "Stage II", "Stage III", "Stage IV"],
                n_samples,
                p=[0.2, 0.3, 0.3, 0.2]
            ),
            "vital_status": np.random.choice(
                ["Alive", "Dead"], n_samples, p=[0.7, 0.3]
            )
        })

        if use_cache:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                clinical_data.to_parquet(cache_file)
            except Exception as e:
                logger.warning(f"Could not cache clinical data: {e}")

        return clinical_data

    async def download_from_cptac_portal(
        self,
        cancer_type: str,
        data_type: str = "proteomics"
    ) -> pd.DataFrame:
        """
        Download data from CPTAC Data Portal

        TODO: Implement actual CPTAC Data Portal integration
        See: https://cptac-data-portal.georgetown.edu/

        Args:
            cancer_type: CPTAC cancer type code
            data_type: Type of data to download

        Returns:
            DataFrame with expression data
        """
        logger.info(
            f"CPTAC download not yet implemented for {cancer_type} "
            f"({data_type})"
        )
        raise NotImplementedError(
            "CPTAC Data Portal integration not yet implemented. "
            "Using mock data for now."
        )
