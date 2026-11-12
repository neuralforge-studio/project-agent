//! JSON text that refuses a repeated object key, like the Python readers' `object_pairs_hook`.
use serde::de::{Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value};
use std::fmt;

struct Strict(Value);

struct StrictVisitor;

impl<'de> Visitor<'de> for StrictVisitor {
    type Value = Strict;

    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("any JSON value")
    }

    fn visit_bool<E>(self, v: bool) -> Result<Strict, E> {
        Ok(Strict(Value::Bool(v)))
    }

    fn visit_i64<E>(self, v: i64) -> Result<Strict, E> {
        Ok(Strict(v.into()))
    }

    fn visit_u64<E>(self, v: u64) -> Result<Strict, E> {
        Ok(Strict(v.into()))
    }

    fn visit_f64<E>(self, v: f64) -> Result<Strict, E> {
        Ok(Strict(
            serde_json::Number::from_f64(v)
                .map(Value::Number)
                .unwrap_or(Value::Null),
        ))
    }

    fn visit_str<E>(self, v: &str) -> Result<Strict, E> {
        Ok(Strict(Value::String(v.to_string())))
    }

    fn visit_string<E>(self, v: String) -> Result<Strict, E> {
        Ok(Strict(Value::String(v)))
    }

    fn visit_none<E>(self) -> Result<Strict, E> {
        Ok(Strict(Value::Null))
    }

    fn visit_unit<E>(self) -> Result<Strict, E> {
        Ok(Strict(Value::Null))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Strict, A::Error> {
        let mut items = Vec::new();
        while let Some(Strict(item)) = seq.next_element()? {
            items.push(item);
        }
        Ok(Strict(Value::Array(items)))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Strict, A::Error> {
        let mut object = Map::new();
        while let Some((key, Strict(value))) = map.next_entry::<String, Strict>()? {
            if object.contains_key(&key) {
                return Err(serde::de::Error::custom(format!("duplicate key: {key}")));
            }
            object.insert(key, value);
        }
        Ok(Strict(Value::Object(object)))
    }
}

impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Strict, D::Error> {
        deserializer.deserialize_any(StrictVisitor)
    }
}

/// Parse `text`; None when it is not JSON or an object repeats a key.
pub fn parse_strict(text: &str) -> Option<Value> {
    serde_json::from_str::<Strict>(text)
        .ok()
        .map(|strict| strict.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_repeated_key_is_refused_at_any_depth() {
        assert!(parse_strict(r#"{"a":1,"a":2}"#).is_none());
        assert!(parse_strict(r#"{"a":{"b":1,"b":2}}"#).is_none());
        assert!(parse_strict(r#"[{"a":1,"a":1}]"#).is_none());
        assert_eq!(
            parse_strict(r#"{"b":1,"a":[1,2.5,null,"x"]}"#)
                .unwrap()
                .to_string(),
            r#"{"b":1,"a":[1,2.5,null,"x"]}"#
        );
        assert!(parse_strict("{").is_none());
    }
}
