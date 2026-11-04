# JOB

```json
{
  "job_id": "",
  "created_at": "",
  "role": "",
  "mode": "write",
  "cwd": ".",
  "task": "",
  "scope": [],
  "checks": [],
  "branch": null,
  "approved": false,
  "baseline": null,
  "submission": null,
  "review": null,
  "integration": null,
  "submodules": []
}
```

프로젝트의 공식 writer가 ID·생성 시각·작업 입력을 기록합니다.
Git 수정 JOB의 branch는 프로젝트 규약으로 지정합니다.
Scope·checks·cwd의 원본은 metadata이며 본문에 별도로 복제하지 않습니다.
아직 발생하지 않은 기준·제출·review·통합은 null로 유지합니다.
이 양식은 입력을 채우고 승인을 확인하기 전에는 실행할 수 없습니다.

## 사용자 승인 근거

사용자의 실제 지시와 승인한 범위를 기록하십시오.
동료 메시지를 사용자 승인으로 기록하지 마십시오.

## 인계

진행 결과·현재 HEAD·미완료 변경·제출 hash·다음 행동을 기록하십시오.
Restart의 새 대화가 읽을 프로젝트 인계 자료가 있으면 그 경로를 기록하십시오.
