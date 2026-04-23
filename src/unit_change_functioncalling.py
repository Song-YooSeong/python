# merged.py
import json
import uuid
import requests
from openai import OpenAI

# =========================
# tools.py 내용 (단위 변환)
# =========================

def convert_temperature(value: float, from_unit: str, to_unit: str):
    if from_unit == to_unit:
        return round(value, 2)
    try:
        if from_unit == "C" and to_unit == "K":
            return round(value + 273.15, 2)
        elif from_unit == "K" and to_unit == "C":
            return round(value - 273.15, 2)
        elif from_unit == "C" and to_unit == "F":
            return round((value * 1.8) + 32, 2)
        elif from_unit == "F" and to_unit == "C":
            return round((value - 32) / 1.8, 2)
        elif from_unit == "K" and to_unit == "F":
            return round(((value - 273.15) * 1.8) + 32, 2)
        elif from_unit == "F" and to_unit == "K":
            return round(((value - 32) / 1.8) + 273.15, 2)
        else:
            return "지원하지 않는 변환입니다."
    except Exception:
        return "변환 중 오류가 발생했습니다."

def convert_flowrate(value: float, from_unit: str, to_unit: str):
    if from_unit == to_unit:
        return round(value, 4)
    if from_unit == "L/min" and to_unit == "m3/h":
        return round(value * 0.06, 4)
    elif from_unit == "m3/h" and to_unit == "L/min":
        return round(value / 0.06, 4)
    else:
        return "지원하지 않는 변환입니다."

def convert_length(value: float, from_unit: str, to_unit: str):
    # 기준 단위: 미터 (m)
    to_meter = {
        "m": 1,
        "cm": 0.01,
        "mm": 0.001,
        "μm": 1e-6,
        "nm": 1e-9,
        "km": 1000,
        "mil": 0.0000254,
    }

    if from_unit not in to_meter or to_unit not in to_meter:
        return "지원하지 않는 변환입니다."

    m_value = value * to_meter[from_unit]
    return round(m_value / to_meter[to_unit], 6)

def convert_angle(value: float, from_unit: str, to_unit: str):
    if from_unit == to_unit:
        return round(value, 6)
    if from_unit == "°" and to_unit == "rad":
        return round(value * 0.0174533, 6)
    elif from_unit == "rad" and to_unit == "°":
        return round(value * 57.2958, 6)
    else:
        return "지원하지 않는 변환입니다."

def convert_pressure(value: float, from_unit: str, to_unit: str):
    to_pa = {
        "Pa": 1,
        "kPa": 1000,
        "MPa": 1_000_000,
        "bar": 100_000,
        "psi": 6894.76,
        "atm": 101325,
        "mmHg": 133.322,
        "hPa": 100,
    }
    if from_unit not in to_pa or to_unit not in to_pa:
        return "지원하지 않는 변환입니다."
    pa_value = value * to_pa[from_unit]
    return round(pa_value / to_pa[to_unit], 6)

def convert_force(value: float, from_unit: str, to_unit: str):
    to_n = {
        "N": 1,
        "kN": 1000,
        "tf": 9806.65,
        "kgf": 9.80665,
    }
    if from_unit not in to_n or to_unit not in to_n:
        return "지원하지 않는 변환입니다."
    n_value = value * to_n[from_unit]
    return round(n_value / to_n[to_unit], 6)

def convert_current(value: float, from_unit: str, to_unit: str):
    to_amp = {
        "A": 1,
        "mA": 0.001,
    }
    if from_unit not in to_amp or to_unit not in to_amp:
        return "지원하지 않는 변환입니다."
    amp_value = value * to_amp[from_unit]
    return round(amp_value / to_amp[to_unit], 6)

def convert_inductance(value: float, from_unit: str, to_unit: str):
    to_h = {
        "H": 1,
        "mH": 0.001,
    }
    if from_unit not in to_h or to_unit not in to_h:
        return "지원하지 않는 변환입니다."
    h_value = value * to_h[from_unit]
    return round(h_value / to_h[to_unit], 6)

def convert_energy(value: float, from_unit: str, to_unit: str):
    factor = {
        "J": 1,
        "kJ": 1_000,
        "MJ": 1_000_000,
        "Wh": 3600,
        "kcal": 4184,
    }
    if from_unit == "eV" or to_unit == "eV":
        if from_unit == "J" and to_unit == "eV":
            return round(value * 6.242e+18, 2)
        elif from_unit == "eV" and to_unit == "J":
            return round(value / 6.242e+18, 2)
        else:
            return "지원하지 않는 변환입니다."
    if from_unit not in factor or to_unit not in factor:
        return "지원하지 않는 변환입니다."
    j_value = value * factor[from_unit]
    return round(j_value / factor[to_unit], 6)

def convert_power(value: float, from_unit: str, to_unit: str):
    factor = {
        "W": 1,
        "kW": 1000,
        "MW": 1_000_000,
        "W·m": 1,
        "kW·m": 1000,
    }
    if from_unit not in factor or to_unit not in factor:
        return "지원하지 않는 변환입니다."
    w_value = value * factor[from_unit]
    return round(w_value / factor[to_unit], 6)

def get_unit_conversion_tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "convert_temperature",
                "description": "온도 단위 변환 (섭씨, 화씨, 절대온도)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string", "enum": ["C", "F", "K"]},
                        "to_unit": {"type": "string", "enum": ["C", "F", "K"]},
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "convert_flowrate",
                "description": "유량 단위 변환 (L/min ↔ m3/h)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string", "enum": ["L/min", "m3/h"]},
                        "to_unit": {"type": "string", "enum": ["L/min", "m3/h"]},
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "convert_angle",
                "description": "각도 변환 함수 (도 ↔ 라디안)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string", "enum": ["°", "rad"]},
                        "to_unit": {"type": "string", "enum": ["°", "rad"]},
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "convert_pressure",
                "description": "압력 단위 변환",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {
                            "type": "string",
                            "enum": ["Pa", "kPa", "MPa", "bar", "psi", "atm", "mmHg", "hPa"],
                        },
                        "to_unit": {
                            "type": "string",
                            "enum": ["Pa", "kPa", "MPa", "bar", "psi", "atm", "mmHg", "hPa"],
                        },
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "convert_force",
                "description": "힘 단위 변환",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string", "enum": ["N", "kN", "tf", "kgf"]},
                        "to_unit": {"type": "string", "enum": ["N", "kN", "tf", "kgf"]},
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "convert_current",
                "description": "전류 단위 변환 (A ↔ mA)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string", "enum": ["A", "mA"]},
                        "to_unit": {"type": "string", "enum": ["A", "mA"]},
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "convert_inductance",
                "description": "인덕턴스 단위 변환 (H ↔ mH)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string", "enum": ["H", "mH"]},
                        "to_unit": {"type": "string", "enum": ["H", "mH"]},
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "convert_energy",
                "description": "에너지 단위 변환 (J, kJ, MJ, Wh, kcal, eV)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string", "enum": ["J", "kJ", "MJ", "Wh", "kcal", "eV"]},
                        "to_unit": {"type": "string", "enum": ["J", "kJ", "MJ", "Wh", "kcal", "eV"]},
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "convert_length",
                "description": "길이 단위 변환 (m, cm, mm, μm, nm, km, mil)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string", "enum": ["m", "cm", "mm", "μm", "nm", "km", "mil"]},
                        "to_unit": {"type": "string", "enum": ["m", "cm", "mm", "μm", "nm", "km", "mil"]},
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "convert_power",
                "description": "전력 단위 변환 (W, kW, MW, W·m, kW·m)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number"},
                        "from_unit": {"type": "string", "enum": ["W", "kW", "MW", "W·m", "kW·m"]},
                        "to_unit": {"type": "string", "enum": ["W", "kW", "MW", "W·m", "kW·m"]},
                    },
                    "required": ["value", "from_unit", "to_unit"],
                },
            },
        },
    ]

function_map = {
    "convert_temperature": convert_temperature,
    "convert_flowrate": convert_flowrate,
    "convert_length": convert_length,
    "convert_angle": convert_angle,
    "convert_pressure": convert_pressure,
    "convert_force": convert_force,
    "convert_current": convert_current,
    "convert_inductance": convert_inductance,
    "convert_energy": convert_energy,
    "convert_power": convert_power,
}

# =========================
# api_executor.py 내용 (HCX 호출)
# =========================

#API_URL = "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005"
#API_KEY = "Bearer nv-"

API_URL = "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005"
API_KEY = "nv-a5f1ea734dde48d3832118b3b6c19011eY1N"

def _ensure_dict_args(args):
    """
    toolCalls의 arguments가 dict 또는 JSON string으로 올 수 있어서 둘 다 처리.
    원본 코드에서는 dict 가정이었음. (안전성 보강)
    """
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            return json.loads(args)
        except Exception:
            # JSON 파싱 실패 시 그대로 반환 (호출 단계에서 에러로 잡힘)
            return args
    return args

def call_hcx_api(user_query: str):
    headers = {        
        "Authorization": f"Bearer {API_KEY}",
        "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


    initial_payload = {
        "model": "HCX-005",
        "messages": [{"role": "user", "content": user_query}],
        "tools": get_unit_conversion_tools(),
        "tool_choice": "auto",
        "topP": 0.8,
        "temperature": 0.5,
        "maxTokens": 2048,
    }

    resp = requests.post(API_URL, headers=headers, json=initial_payload)
    data = resp.json()
    
    if resp.status_code != 200:
        print(f"[API 오류]: {resp.status_code}", resp.text)
        return None

    # Step 1: toolCalls 확인
    tool_calls = data.get("result", {}).get("message", {}).get("toolCalls", [])

    if not tool_calls:
        content = data.get("result", {}).get("message", {}).get("content", "")
        print("[최종 응답]:\n" + content.strip())
        return content

    # Step 2: 함수 호출 & 결과 처리
    messages = [{"role": "user", "content": user_query}]
    for t in tool_calls:
        fn = t["function"]["name"]
        args = _ensure_dict_args(t["function"]["arguments"])
        print(f"[함수 호출]: {fn}({args})")
        try:
            if not isinstance(args, dict):
                raise ValueError(f"arguments가 dict가 아님: {type(args)} / {args}")
            result = function_map[fn](**args)
        except Exception as e:
            result = f"[함수 실행 오류]: {e}"
        print(f"[함수 결과]: {result}")

        messages.append(
            {
                "role": "assistant",
                "content": "",
                "toolCalls": [t],
            }
        )
        messages.append(
            {
                "role": "tool",
                "toolCallId": t["id"],
                "content": json.dumps(result),
            }
        )

    # Step 3: follow-up 요청
    follow_up = {
        "model": "HCX",
        "messages": messages,
        "tool_choice": "auto",
        "topP": 0.8,
        "temperature": 0.5,
        "maxTokens": 2048,
    }
    res2 = requests.post(API_URL, headers=headers, json=follow_up)
    if res2.status_code != 200:
        print(f"[API 오류 - FollowUp]: {res2.status_code}", res2.text)
        return None
    data2 = res2.json()

    final = data2.get("result", {}).get("message", {}).get("content", "")
    print("[최종 응답]:\n" + final.strip())
    return final

# =========================
# main.py 내용 (CLI 엔트리)
# =========================

def main():
    while True:
        q = input("변환 질문을 입력하세요:\n")
        resp = call_hcx_api(q)
        if resp is None:
            print("[응답 없음]")

if __name__ == "__main__":
    main()
