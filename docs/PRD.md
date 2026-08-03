**DiamondScout AI 최종 PRD**

**1. 서비스명**  
**DiamondScout AI**  
딥러닝 기반 타석 승부 시뮬레이션 + LLM 야구 전력분석 코칭 플랫폼

**2. 서비스 한 줄 정의**  
DiamondScout AI는 투수와 타자가 같은 타석 상황을 각자의 관점에서 분석할 수 있도록, 딥러닝이 다음 구종과 위험도를 예측하고 LLM이 전략 의도까지 반영해 전력분석 리포트와 즉각 질의응답을 제공하는 실전형 야구 AI 분석 서비스다.

**3. 핵심 컨셉**
기존 PitcherIQ가 “다음 구종 예측” 중심이었다면, DiamondScout AI는 이를 확장해 **타석 승부 의사결정 서비스**로 만든다.

- 투수 입장: 내 구종과 코스가 상대에게 읽힐 위험 분석
- 타자 입장: 상대 투수의 다음 공과 공략 전략 예측
- LLM 역할: 사용자의 자연어 전략 의도를 이해하고 코칭 리포트 생성
- RAG 역할: 선수/매치업/구종별 근거 데이터를 검색해 답변 근거 제공

**4. 수업자료 활용 계획**

| 수업자료 기술 | 서비스 적용 방식 |
|---|---|
| Hugging Face | `sentence-transformers/all-MiniLM-L6-v2` 임베딩, 전략 코멘트 벡터화, RAG 검색 |
| Transformer 예제 | 사용자 전략 의도 분류 모델로 응용 |
| Tokenizing / Embedding | 자연어 코멘트를 모델 입력으로 변환 |
| Ollama | 로컬 LLM으로 코칭 리포트와 Q&A 답변 생성 |
| LangChain Prompt / Chain | 분석 결과 + 검색 근거 + 사용자 질문 연결 |
| FAISS | 전력분석 텍스트와 CSV 요약 데이터를 벡터DB로 저장 |
| RAG | 선수/구종/매치업 근거를 검색해 LLM 답변에 삽입 |
| Gradio | 투수 모드, 타자 모드, 시뮬레이터, 채팅 UI 구현 |
| STT/TTS 예제 | 선택 확장: 음성 코치 메모 입력, 리포트 음성 출력 |

**5. 주요 사용자 모드**

**A. 투수 모드**  
목적: 상대 타자에게 읽히지 않는 구종과 코스를 선택한다.

입력:
- 투수 선택
- 상대 타자 선택
- 이닝, 점수 차, 주자 상황, 아웃카운트, 볼카운트
- 최근 5구 구종/위치/결과
- 내가 던지려는 구종
- 전략 의도 코멘트  
  예: `고의4구 느낌으로 빼고 싶다`, `장타만 피하고 싶다`

출력:
- 다음 구종 Top-3 예측
- 패턴 노출 위험도
- Pitch Disguise Score
- 추천 구종/대체 구종
- 3x3 스트라이크존 추천 히트맵
- 포수 사인 추천
- LLM 투수/포수 코칭 리포트

**B. 타자 모드**  
목적: 상대 투수의 다음 공을 예측하고 타격 접근법을 세운다.

입력:
- 상대 투수 선택
- 타자 정보: 좌타/우타
- 현재 경기 상황
- 최근 5구
- 타자 전략 코멘트  
  예: `출루만 해도 된다`, `초구 직구를 노리고 싶다`

출력:
- 예상 구종 Top-3
- 예상 도착 위치
- 예상 공 궤적
- 노릴 구종
- 참아야 할 유인구
- 타자 시점 브리핑
- LLM 타격 코칭 리포트

**C. 타석 시뮬레이션 모드**  
사용자가 공 하나씩 입력하면 볼카운트와 최근 패턴이 갱신되고, 매 투구마다 AI 분석이 다시 생성된다.

```text
1구 FF 스트라이크
2구 SL 볼
3구 CH 파울

현재 카운트: 1-2
AI 분석: 낮은 존 변화구 유인 가능성이 증가했습니다.
```

**6. Instant Scout Q&A**  
리포트가 생성된 뒤, 사용자가 궁금한 점을 바로 물어볼 수 있는 작은 채팅 UI를 제공한다.

예시 질문:
```text
왜 포심이 위험해?
체인지업 대신 슬라이더는 어때?
볼넷을 감수하면 어느 코스가 좋아?
타자 입장에서 지금 참아야 할 공은 뭐야?
```

답변 근거:
- 현재 경기 상황
- 최근 5구
- 딥러닝 예측 결과
- 추천 구종/코스
- 위험도/위장 점수
- 사용자 전략 코멘트
- RAG로 검색한 전력분석 근거
- 방금 생성된 리포트

**7. 핵심 기능**

| 기능 | 설명 |
|---|---|
| Next Pitch Prediction | 최근 시퀀스와 경기 상황 기반 다음 구종 예측 |
| Intent Parser | 자연어 전략 코멘트를 목표/위험 허용도/승부 의도로 변환 |
| Pattern Exposure Risk | 투구 패턴이 상대에게 읽힐 위험도 계산 |
| Pitch Disguise Score | 구종 예측이 한쪽에 몰릴수록 낮아지는 위장 점수 |
| Location Heatmap | 투수 모드 3x3 존별 추천/위험 히트맵 |
| Trajectory View | 타자 모드 공 궤적과 존 통과 예상 위치 시각화 |
| Batter Reaction Prediction | 스윙/참기/헛스윙/인플레이 가능성 예측 |
| Contact Risk Model | 장타/약한 타구/땅볼/뜬공 위험 분석 |
| RAG Strategy Q&A | FAISS 검색 기반 즉각 질의응답 |
| LLM Scouting Report | 투수/포수/타자 관점 리포트 생성 |

**8. 필요한 데이터**

| 범주 | 주요 데이터 |
|---|---|
| 투구 기본 | `pitch_type`, `pitch_name`, `release_speed`, `release_spin_rate` |
| 궤적 | `release_pos_x/y/z`, `vx0`, `vy0`, `vz0`, `ax`, `ay`, `az` |
| 움직임/위치 | `pfx_x`, `pfx_z`, `plate_x`, `plate_z`, `zone`, `sz_top`, `sz_bot` |
| 경기 상황 | `balls`, `strikes`, `outs_when_up`, `inning`, `on_1b`, `on_2b`, `on_3b`, `bat_score`, `fld_score` |
| 투구 결과 | `description`, `type` |
| 타석 결과 | `events` |
| 타구 품질 | `launch_speed`, `launch_angle`, `hit_distance`, `bb_type` |
| 기대 지표 | `estimated_woba_using_speedangle`, `woba_value`, `delta_run_exp` |
| 매치업 | `pitcher`, `batter`, `player_name`, `stand`, `p_throws` |
| 비정형 입력 | 전략 코멘트, 코치 메모, 경기 운영 목표 |

**9. UI 요구사항**

투수 모드:
- 포수 시점 3x3 스트라이크존 히트맵
- 초록: 추천, 노랑: 주의, 빨강: 위험
- 셀 클릭 시 추천 이유 표시
- 구종별 필터 제공
- `승부구`, `유인구`, `낭비구`, `장타위험` 태그 표시

타자 모드:
- 타자 시점 배경
- 릴리즈 포인트 → 공 궤적 → 존 통과 예상 위치 표시
- 구종별 궤적 색상 구분
- 노릴 위치와 참아야 할 위치 표시
- `스윙 추천` / `참기 추천` 표시

공통:
- 전략 코멘트 입력창
- Top-3 예측 확률 카드
- 위험도/위장 점수 게이지
- 전력분석 리포트 카드
- 타석 히스토리 타임라인
- 리포트 하단의 소형 Q&A 채팅창

**10. 구현 구조**

```text
diamondscout_ai/
├── app.py
├── models/
│   ├── next_pitch_model.py
│   ├── intent_classifier.py
│   ├── risk_model.py
│   └── trajectory_model.py
├── services/
│   ├── pitcher_mode_service.py
│   ├── batter_mode_service.py
│   ├── atbat_simulator.py
│   ├── rag_service.py
│   └── llm_scout.py
├── ui/
│   ├── zone_heatmap.py
│   ├── trajectory_view.py
│   └── instant_chat.py
└── data/
```

**11. 전체 처리 흐름**

```text
사용자 입력
→ 경기 상황 + 최근 5구 + 전략 코멘트 정리
→ 딥러닝 모델로 다음 구종/위험도 예측
→ Hugging Face 임베딩으로 관련 전력분석 데이터 검색
→ FAISS/RAG로 근거 문서 추출
→ Ollama LLM이 예측 결과와 검색 근거를 합쳐 리포트 생성
→ 사용자가 추가 질문하면 Instant Scout Q&A가 같은 컨텍스트로 답변
```

**12. 리포트 형식**

```text
1. 현재 상황 요약
2. 딥러닝 예측 결과
3. 사용자 전략 의도 해석
4. RAG 기반 참고 근거
5. 위험 요소
6. 추천 구종/코스
7. 대안 전략
8. 한 줄 스카우팅 메시지
```

**13. 시연 방식**

수업자료와 맞춰 Gradio 기반으로 시연한다.

```python
demo.launch(server_port=7861, share=True, server_name="0.0.0.0")
```

탭 구성:
- 투수 모드
- 타자 모드
- 타석 시뮬레이터
- Instant Scout Q&A

**14. 성공 기준**

- 다음 구종 Top-3 정확도 80% 이상 목표
- 리포트마다 딥러닝 결과, 경기 상황, 전략 코멘트, RAG 근거 중 최소 2개 이상 반영
- 투수 모드와 타자 모드가 같은 상황을 반대 관점으로 해석
- 사용자가 타석을 진행하면 분석 결과가 즉시 갱신
- 리포트 이후 Q&A에서 현재 분석 컨텍스트 기반 답변 가능
- 수업자료의 Hugging Face, RAG, Ollama, Gradio 활용 구조가 발표에서 명확히 드러남

**15. 발표용 최종 설명**

DiamondScout AI는 수업에서 배운 Hugging Face 임베딩, FAISS 기반 RAG, Ollama 로컬 LLM, Gradio UI, Transformer 구조를 야구 전력분석 서비스에 적용한 프로젝트입니다. 딥러닝 모델은 다음 구종과 위험도를 예측하고, LLM은 사용자의 자연어 전략 의도와 검색된 전력분석 근거를 바탕으로 투수/타자 관점의 스카우팅 리포트와 즉각 질의응답을 제공합니다.
