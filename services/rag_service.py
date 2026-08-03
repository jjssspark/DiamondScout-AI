"""
DiamondScout AI - RAG(검색 증강 생성) 서비스
야구 전력분석 도메인 설명 문서 + 최신 분석 결과(ScoutingService.analyze() 반환값)를
HuggingFace 임베딩으로 벡터화하고 FAISS로 유사도 검색해, LLMScout에 전달할 컨텍스트
조각을 만든다.
"""

import glob
import os
import re

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from services.scouting_service import pitch_label_kr

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "knowledge")


def _load_knowledge_chunks(knowledge_dir: str = KNOWLEDGE_DIR) -> list[str]:
    """data/knowledge/*.md(직접 작성한 코칭 룰 문서)를 "## 소제목" 단위로 쪼개 검색 가능한
    텍스트 조각으로 만든다. 파일 전체를 하나로 넣으면 질문과 무관한 부분까지 컨텍스트에
    섞여 들어가므로, 섹션 단위로 잘라야 retrieve()의 의미 검색이 더 정확해진다."""
    chunks: list[str] = []
    for path in sorted(glob.glob(os.path.join(knowledge_dir, "*.md"))):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        sections = re.split(r"\n##\s+", text)
        for section in sections:
            section = section.strip()
            if not section or section.startswith("# "):
                continue  # 최상단 "# 제목" 한 줄짜리 섹션은 내용이 없어 제외
            lines = section.split("\n", 1)
            heading = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            if body:
                chunks.append(f"[{heading}] {body}")
    return chunks

# 야구 전력분석 도메인 설명 (고정 지식베이스). data/processed/README.md와
# services/scouting_service.py의 규칙 정의를 사람이 읽을 수 있는 문장으로 옮긴 것.
PITCH_LABEL_DESCRIPTIONS = {
    "FF": "포심 패스트볼(4-Seam Fastball). 가장 빠르고 직선적인 구종으로 대부분의 투수가 주력으로 사용한다.",
    "SI": "싱커(Sinker). 타자 앞에서 아래로 떨어지며 땅볼을 유도하는 패스트볼 계열 구종.",
    "SL": "슬라이더(Slider). 옆으로 휘며 헛스윙을 유도하는 변화구.",
    "CH": "체인지업(Changeup). 패스트볼과 비슷한 폼으로 구속을 늦춰 타이밍을 뺏는 구종.",
    "ST": "스위퍼(Sweeper). 슬라이더보다 옆 무브먼트가 큰 변화구.",
    "FC": "커터(Cutter). 패스트볼에 약간의 횡 무브먼트를 더한 구종.",
    "CU": "커브(Curveball). 큰 낙차로 떨어지는 변화구.",
    "FS": "스플리터(Splitter/Forkball). 급격히 떨어지는 오프스피드 구종.",
    "KC": "너클커브(Knuckle-curve). 손가락을 세워 던지는 변형 커브.",
    "SV": "슬러브(Slurve). 슬라이더와 커브 중간 성격의 변화구.",
    "OTHER": "그 외 세부 분류되지 않은 구종.",
}

DOMAIN_DOCS: list[str] = [
    "zone_cell은 스트라이크존을 3x3 격자로 나눈 좌표다. 1~9는 존 안쪽(1=하단좌측, 5=한가운데, 9=상단우측), 0은 존 밖을 의미한다.",
    "pattern_exposure_risk(패턴 노출 위험)는 예측된 top1 구종의 확률이다. 값이 높을수록 상대가 다음 구종을 쉽게 예측할 수 있다는 뜻이다.",
    "extra_base_hit_risk(장타 위험)와 home_run_risk(홈런 위험)는 예측된 top3 구종에 대한 해당 투수의 실제 장타/홈런 허용 비율 평균이다.",
    "walk_risk(볼넷 위험)는 예측된 top3 구종이 볼(ball)로 판정된 비율의 평균이다. 값이 높을수록 볼넷으로 이어질 가능성이 크다.",
    "사용자 전략 코멘트에 '빼고', '고의4구', '볼넷' 같은 표현이 있으면 evasive_pitching으로 해석되어, 3x3 히트맵에서 존 정중앙 확률을 낮추고 존 모서리 확률을 높이는 방향으로 반영된다.",
    "사용자 전략 코멘트에 '적극적으로', '존 안으로', '정면승부' 같은 표현이 있으면 aggressive_pitching으로 해석되어, 3x3 히트맵에서 존 정중앙 확률을 높이는 방향으로 반영된다.",
    "추천 구종(recommended_pitch)은 RandomForest 모델이 예측한 확률이 가장 높은 구종이다. 피해야 할 구종(avoid_pitch)은 해당 투수가 실제로 던지는 구종 중 예측 확률이 가장 낮은 구종이다.",
    "타자 모드의 노릴 코스(target_zone)와 대응 전략(counter_strategy)은 투수 모드와 동일한 top3 예측 결과에, 사용자 코멘트 해석 결과를 반영해 만들어진다.",
] + [f"{label}: {desc}" for label, desc in PITCH_LABEL_DESCRIPTIONS.items()] + _load_knowledge_chunks()


def analysis_result_to_chunks(result: dict) -> list[str]:
    """ScoutingService.analyze() 결과 dict를 검색 가능한 텍스트 조각들로 변환한다."""
    chunks: list[str] = []

    top3 = result.get("predicted_top3_pitches") or []
    if top3:
        top3_text = ", ".join(
            f"{pitch_label_kr(item['pitch_label'])}({item['pitch_label']}) {item['probability']:.1%}" for item in top3
        )
        chunks.append(f"이번 분석의 다음 구종 Top-3 예측: {top3_text}.")

    risk_summary = result.get("risk_summary") or {}
    if risk_summary:
        chunks.append(
            "이번 분석의 위험도 요약: "
            f"패턴 노출 위험 {risk_summary.get('pattern_exposure_risk')}, "
            f"장타 위험 {risk_summary.get('extra_base_hit_risk')}, "
            f"홈런 위험 {risk_summary.get('home_run_risk')}, "
            f"볼넷 위험 {risk_summary.get('walk_risk')}."
        )

    interpretation = result.get("user_comment_interpretation") or {}
    if interpretation.get("raw_comment"):
        chunks.append(
            f"사용자 코멘트 '{interpretation.get('raw_comment')}'는 다음과 같이 해석되었다: "
            f"{interpretation.get('summary', '')}."
        )

    pitcher_result = result.get("pitcher_mode_result")
    if pitcher_result:
        recommended = pitcher_result.get("recommended_pitch")
        avoid = pitcher_result.get("avoid_pitch")
        avoid_text = f"{pitch_label_kr(avoid)}({avoid})" if avoid else "없음"
        chunks.append(
            f"투수 모드 결과: 추천 구종은 {pitch_label_kr(recommended)}({recommended}), "
            f"피해야 할 구종은 {avoid_text}이다. "
            f"코칭 메시지: {pitcher_result.get('coaching_message')}"
        )
        batter_weakness = pitcher_result.get("batter_weakness")
        if batter_weakness and batter_weakness.get("summary"):
            chunks.append(f"상대 타자 약점 요약: {batter_weakness['summary']}")

    batter_result = result.get("batter_mode_result")
    if batter_result:
        chunks.append(
            f"타자 모드 결과: 노릴 코스는 {batter_result.get('target_zone')}이다. "
            f"대응 전략: {batter_result.get('counter_strategy')}"
        )
        pitcher_pattern = batter_result.get("pitcher_pattern")
        if pitcher_pattern and pitcher_pattern.get("summary"):
            chunks.append(f"상대 투수 패턴 요약: {pitcher_pattern['summary']}")

    return chunks


class RAGService:
    """HuggingFace 임베딩 + FAISS 인메모리 인덱스로 도메인 문서를 검색한다.

    도메인 지식 문서(구종/용어 설명 + data/knowledge/*.md 코칭 룰 섹션)는 FAISS 의미 검색으로
    relevant한 것만 추리지만, 최신 분석 결과
    조각(4~5개, analysis_result_to_chunks)은 코퍼스가 작아 임베딩 유사도만으로는 상위 k에서
    밀려날 수 있어 질문마다 항상 전부 포함한다 ("이번 분석"에 대한 Q&A가 핵심 기능이므로).
    """

    def __init__(self, embedding_model_name: str = EMBEDDING_MODEL_NAME):
        self.embedding_model = SentenceTransformer(embedding_model_name)
        self.analysis_chunks: list[str] = []
        self.domain_index = self._build_domain_index()

    def _embed(self, texts: list[str]) -> np.ndarray:
        vectors = self.embedding_model.encode(texts, normalize_embeddings=True)
        return np.asarray(vectors, dtype="float32")

    def _build_domain_index(self) -> faiss.Index:
        # 내적(IP) 인덱스 + 정규화 임베딩 조합으로 코사인 유사도 검색을 구현한다.
        vectors = self._embed(DOMAIN_DOCS)
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        return index

    def build_index(self, analysis_result: dict | None) -> None:
        """최신 분석 결과에서 문서 조각을 뽑아 저장한다 (도메인 인덱스는 고정, 재사용)."""
        self.analysis_chunks = analysis_result_to_chunks(analysis_result) if analysis_result else []

    def retrieve(self, query: str, k: int = 3) -> list[str]:
        """현재 분석 결과 조각(전체) + 질의와 가장 관련 있는 도메인 지식 k개를 합쳐 반환."""
        domain_hits: list[str] = []
        if self.domain_index is not None and DOMAIN_DOCS:
            query_vector = self._embed([query])
            top_k = min(k, len(DOMAIN_DOCS))
            _, indices = self.domain_index.search(query_vector, top_k)
            domain_hits = [DOMAIN_DOCS[i] for i in indices[0] if i != -1]
        return self.analysis_chunks + domain_hits
