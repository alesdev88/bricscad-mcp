;; Runs requests from the queue folder, one at a time. See bridge.py for the protocol.
(vl-load-com)

(setq *mcp-quiet-seconds* 120.0)
(setq *mcp-pending-error* nil)

(defun mcp:path (name) (strcat *mcp-dir* name))

(defun mcp:write-file (path text / file)
  (setq file (open path "w" "utf8"))
  (princ text file)
  (close file)
)

;; ---- Helpers tools rely on ----

(defun mcp:documents () (vla-get-documents (vlax-get-acad-object)))
(defun mcp:active-document () (vla-get-activedocument (vlax-get-acad-object)))
(defun mcp:current-drawing () (getvar "DWGNAME"))

(defun mcp:unsaved-count (/ count)
  (setq count 0)
  (vlax-for document (mcp:documents)
    (if (= (vla-get-saved document) :vlax-false) (setq count (1+ count)))
  )
  count
)

;; Sets variables, evaluates a source string, and always restores them.
(defun mcp:with-vars (pairs source / saved result)
  (setq saved (mapcar (function (lambda (pair) (list (car pair) (getvar (car pair))))) pairs))
  (foreach pair pairs (setvar (car pair) (cadr pair)))
  (setq result (vl-catch-all-apply 'eval (list (read source))))
  (mcp:cancel-command)
  (foreach pair saved (setvar (car pair) (cadr pair)))
  (if (vl-catch-all-error-p result)
    (progn
      (setq *mcp-pending-error* (vl-catch-all-error-message result))
      (exit)
    )
  )
  result
)

(defun mcp:cancel-command (/ tries)
  (setq tries 0)
  (while (and (> (getvar "CMDACTIVE") 0) (< tries 5))
    (command)
    (setq tries (1+ tries))
  )
)

;; ---- Time ----

;; vl-file-systime gives (year month weekday day hour minute second ms).
(defun mcp:systime-seconds (time / y m d a yy mm)
  (setq y (nth 0 time) m (nth 1 time) d (nth 3 time)
        a (/ (- 14 m) 12)
        yy (- (+ y 4800) a)
        mm (- (+ m (* 12 a)) 3))
  (+ (* 86400.0 (+ d (/ (+ (* 153 mm) 2) 5) (* 365 yy) (/ yy 4) (- (/ yy 100)) (/ yy 400) -32045))
     (* 3600.0 (nth 4 time))
     (* 60.0 (nth 5 time))
     (nth 6 time))
)

;; The heartbeat was just written, so its time stands in for the current time.
(defun mcp:server-quiet-p (/ alive now)
  (setq alive (vl-file-systime (mcp:path "server.alive"))
        now (vl-file-systime (mcp:path "heartbeat")))
  (and alive now
       (> (- (mcp:systime-seconds now) (mcp:systime-seconds alive)) *mcp-quiet-seconds*))
)

;; ---- Requests ----

(defun mcp:millis (/ value)
  (setq value (vl-catch-all-apply 'getvar '("MILLISECS")))
  (if (= (type value) 'INT) value 0)
)

(defun mcp:reply-text (id ok result message elapsed)
  (strcat "{\"id\":" (mcp:json-string id)
          ",\"ok\":" (if ok "true" "false")
          ",\"result\":" result
          ",\"error\":" (if message (mcp:json-string message) "null")
          ",\"elapsed_ms\":" (itoa elapsed)
          "}")
)

(defun mcp:run-request (name / id request running started value failed message encoded temporary)
  (setq id (vl-filename-base name)
        request (mcp:path name)
        running (mcp:path (strcat id ".run")))
  (if (vl-file-rename request running)
    (progn
      (setq started (mcp:millis)
            *mcp-pending-error* nil
            value (vl-catch-all-apply 'load (list running))
            failed (vl-catch-all-error-p value))
      (if failed
        (setq message (cond (*mcp-pending-error*) ((vl-catch-all-error-message value)))))
      (mcp:cancel-command)
      (if (not failed)
        (progn
          (setq encoded (vl-catch-all-apply 'mcp:json (list value)))
          (if (vl-catch-all-error-p encoded)
            (setq failed T
                  message (strcat "Could not encode the result: " (vl-catch-all-error-message encoded))
                  encoded "null"))
        )
        (setq encoded "null")
      )
      (setq temporary (mcp:path (strcat id ".reply")))
      (mcp:write-file temporary
        (mcp:reply-text id (not failed) encoded message (- (mcp:millis) started)))
      (vl-file-rename temporary (mcp:path (strcat id ".json")))
      (vl-file-delete running)
    )
  )
)

;; ---- Loop ----

(defun mcp:listen (directory / state)
  (setq *mcp-dir* directory)
  (while (null state)
    (mcp:write-file (mcp:path "heartbeat") "beat")
    (cond
      ((findfile (mcp:path "quit.flag")) (setq state 'quit))
      ((mcp:server-quiet-p) (setq state 'quiet))
      (T
       (foreach name (vl-sort (vl-directory-files *mcp-dir* "*.lsp" 1) '<)
         (mcp:run-request name)
       )
       (command "_.DELAY" 250)
      )
    )
  )
  (mcp:quit-if-safe)
  (princ)
)

;; Called on request and when the server has gone quiet, so no idle copy is left behind.
;; Never prompts: stays open if there is work to keep and nobody asked to discard it.
(defun mcp:quit-if-safe ()
  (cond
    ((findfile (mcp:path "discard.flag")) (command "_.QUIT" "_Y"))
    ((= (mcp:unsaved-count) 0) (command "_.QUIT"))
  )
)
