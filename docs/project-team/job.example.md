# JOB J-20261103-07

```json
{
  "job_id": "J-20261103-07",
  "created_at": "2026-11-03T10:00:00+09:00",
  "role": "backend",
  "mode": "write",
  "cwd": ".",
  "task": "요청 범위의 API 오류를 수정합니다.",
  "scope": ["수정 대상 파일을 실제 프로젝트 경로로 지정합니다."],
  "checks": ["실제 대상에 대응하는 focused check 명령을 지정합니다."],
  "branch": "job/J-20261103-07",
  "approved": false,
  "baseline": null,
  "submission": null,
  "review": null,
  "integration": null,
  "submodules": []
}
```

이 예제의 경로·명령·승인은 설명용입니다.
Leader는 실제 대상과 사용자 승인 근거로 교체한 뒤 공식 writer로 생성합니다.
실제 승인 확인 전에는 approved를 true로 바꾸지 않습니다.
Haroo에서는 task 원본으로부터 이 전달 문서를 생성합니다.

## 사용자 승인 근거

실제 사용자 지시와 승인된 작업 범위를 기록합니다.
동료 메시지를 사용자 승인으로 기록하지 않습니다.

## 완료 기준

1. 지정한 결함을 수정합니다.
2. 해당 결함과 직접 영향 검증을 통과합니다.
3. 실제 제출 hash와 검증 결과를 Leader에게 보고합니다.

## 인계

진행 결과·미완료 항목·제출 hash·다음 행동을 기록합니다.
Restart의 새 대화는 이 문서와 프로젝트 인계 자료를 읽습니다.
제출·review·통합의 판정 기록은 위 metadata의 submission·review·integration을 사용합니다.
아직 발생하지 않은 결과는 null로 유지합니다.
