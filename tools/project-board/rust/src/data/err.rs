//! The error of the Python `agent_session.errors.SessionError`: a code and the message the Board shows.
use std::fmt;

#[derive(Clone, Debug, PartialEq)]
pub struct SessionError {
    pub code: &'static str,
    pub message: String,
}

pub type Res<T> = Result<T, SessionError>;

pub fn error(code: &'static str, message: impl Into<String>) -> SessionError {
    SessionError {
        code,
        message: message.into(),
    }
}

impl fmt::Display for SessionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}
