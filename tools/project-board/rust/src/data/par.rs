//! A small parallel map for the first read, where file system latency (not CPU) decides the time.
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

/// `items.iter().map(f)` on up to `threads` threads; the results keep the order of `items`.
pub fn par_map<T: Sync, R: Send>(
    items: &[T],
    threads: usize,
    f: impl Fn(&T) -> R + Sync,
) -> Vec<R> {
    if threads <= 1 || items.len() < 2 {
        return items.iter().map(&f).collect();
    }
    let next = AtomicUsize::new(0);
    let done: Mutex<Vec<(usize, R)>> = Mutex::new(Vec::with_capacity(items.len()));
    std::thread::scope(|scope| {
        for _ in 0..threads.min(items.len()) {
            scope.spawn(|| loop {
                let index = next.fetch_add(1, Ordering::Relaxed);
                if index >= items.len() {
                    break;
                }
                let result = f(&items[index]);
                done.lock().unwrap().push((index, result));
            });
        }
    });
    let mut done = done.into_inner().unwrap();
    done.sort_by_key(|entry| entry.0);
    done.into_iter().map(|entry| entry.1).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn results_keep_the_input_order() {
        let items: Vec<u32> = (0..100).collect();
        assert_eq!(
            par_map(&items, 8, |n| n * 2),
            items.iter().map(|n| n * 2).collect::<Vec<_>>()
        );
        assert_eq!(par_map(&items[..1], 8, |n| n + 1), vec![1]);
    }
}
