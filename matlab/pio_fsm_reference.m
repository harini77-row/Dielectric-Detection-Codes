%PIO_FSM_REFERENCE Reference behaviour for the three Stateflow charts:
%   (1) Record Builder  (2) Consistency Comparator  (3) DMA Request Generator
% Each is written as an explicit state machine stepped once per tick so the
% Stateflow charts can be built state-for-state from it and checked against
% the same trace. Invariant checked: COMMIT -> comparator token for that
% record; no token -> no commit, no frame.
% Not simulated (deferred to logic-analyser capture): real PIO instruction
% timing, DREQ/DMA bus arbitration, SPI timing.
clear; rng(3);
P = pgdd_params();
N = 5000;
% stimulus: view A/B code pairs with occasional faults
ma = 14000 + randi(4000, N, 1); pa = 9000 + randi(4000, N, 1);
dm = round(20 * randn(N, 1)); dp = round(20 * randn(N, 1));
hit = rand(N, 1) < 0.15; dm(hit) = dm(hit) + 300 * sign(randn(sum(hit), 1));
lock = rand(N, 1) > 0.03;
mb = ma + dm; pb = pa + dp;

% ---- chart state
rb.state = 'IDLE';   % Record Builder: IDLE -> VIEW_A -> PARK -> VIEW_B -> SEAL -> PUSH
cmp.state = 'WAIT';  % Comparator: WAIT -> MAG -> PHASE -> EMIT | DROP
dq.state = 'ARMED';  % DMA Request Gen: ARMED -> TOKEN -> COPY -> DONE | TIMEOUT
commits = 0; tokens = 0; frames = 0; violations = 0;
for k = 1:N
    % (1) Record Builder: assemble and hand 8 grid words to the comparator
    rb.state = 'VIEW_A'; rb.state = 'PARK'; rb.state = 'VIEW_B'; rb.state = 'SEAL';
    [~, w] = consistency_gate(P, ma(k), mb(k), pa(k), pb(k), ~lock(k));
    rb.state = 'PUSH';
    % (2) Comparator
    cmp.state = 'MAG';
    mag_ok = (w(1) == w(2)) || (w(3) == w(4));
    if mag_ok
        cmp.state = 'PHASE';
        ph_ok = (w(5) == w(6)) || (w(7) == w(8));
        if ph_ok, cmp.state = 'EMIT'; else, cmp.state = 'DROP'; end
    else
        cmp.state = 'DROP';
    end
    token = strcmp(cmp.state, 'EMIT');
    tokens = tokens + token;
    % (3) DMA request generator: paced only by the token
    if token
        dq.state = 'TOKEN'; dq.state = 'COPY'; dq.state = 'DONE';
        commits = commits + 1; frames = frames + 1;
    else
        dq.state = 'TIMEOUT';           % CPU aborts; slot never written
    end
    % invariant
    if strcmp(dq.state, 'DONE') && ~token, violations = violations + 1; end
    expected = consistency_gate(P, ma(k), mb(k), pa(k), pb(k), ~lock(k));
    if token ~= expected, violations = violations + 1; end
    rb.state = 'IDLE'; cmp.state = 'WAIT'; dq.state = 'ARMED';
end
fprintf('records %d: tokens %d, commits %d, SPI frames %d, rejected %d, violations %d\n', ...
    N, tokens, commits, frames, N - commits, violations);
assert(violations == 0 && commits == tokens && frames == commits);
