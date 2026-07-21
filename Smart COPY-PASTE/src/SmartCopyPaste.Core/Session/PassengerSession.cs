namespace SmartCopyPaste.Core.Session;

public enum SessionMutationStatus
{
    Succeeded,
    Locked,
    Empty,
    BoundaryReached,
    NotFound,
}

public sealed record SessionMutationResult(
    SessionMutationStatus Status,
    PassengerProfile? Active,
    int ActiveIndex,
    long Generation)
{
    public bool Changed => Status == SessionMutationStatus.Succeeded;
}

/// <summary>
/// Thread-safe, non-persistent passenger collection. Navigation never wraps and a
/// locked active passenger cannot be replaced or switched.
/// </summary>
public sealed class PassengerSession
{
    private readonly object _gate = new();
    private PassengerProfile[] _profiles = [];
    private int _activeIndex = -1;
    private bool _locked;
    private long _generation;

    public IReadOnlyList<PassengerProfile> Profiles
    {
        get
        {
            lock (_gate)
            {
                return Array.AsReadOnly(_profiles.ToArray());
            }
        }
    }

    public PassengerProfile? Active
    {
        get
        {
            lock (_gate)
            {
                return ActiveUnsafe;
            }
        }
    }

    public int ActiveIndex
    {
        get
        {
            lock (_gate)
            {
                return _activeIndex;
            }
        }
    }

    public bool Locked
    {
        get
        {
            lock (_gate)
            {
                return _locked;
            }
        }
        set
        {
            lock (_gate)
            {
                if (_locked != value)
                {
                    _locked = value;
                    _generation++;
                }
            }
        }
    }

    public long Generation
    {
        get
        {
            lock (_gate)
            {
                return _generation;
            }
        }
    }

    public SessionMutationResult SetProfiles(
        IEnumerable<PassengerProfile> profiles,
        int activeIndex = 0)
    {
        ArgumentNullException.ThrowIfNull(profiles);
        PassengerProfile[] materialized = profiles.ToArray();
        if (materialized.Length == 0)
        {
            return Clear();
        }

        if (materialized.Length > 100)
        {
            throw new ArgumentOutOfRangeException(
                nameof(profiles),
                "A temporary session supports at most 100 passengers.");
        }

        if (activeIndex < 0 || activeIndex >= materialized.Length)
        {
            throw new ArgumentOutOfRangeException(nameof(activeIndex));
        }

        if (materialized.Select(profile => profile.ProfileId).Distinct().Count()
            != materialized.Length)
        {
            throw new ArgumentException(
                "Passenger profile identifiers must be unique.",
                nameof(profiles));
        }

        lock (_gate)
        {
            if (_locked && _profiles.Length > 0)
            {
                return ResultUnsafe(SessionMutationStatus.Locked);
            }

            _profiles = materialized.ToArray();
            _activeIndex = activeIndex;
            _locked = false;
            _generation++;
            return ResultUnsafe(SessionMutationStatus.Succeeded);
        }
    }

    public SessionMutationResult Next()
    {
        lock (_gate)
        {
            if (_profiles.Length == 0)
            {
                return ResultUnsafe(SessionMutationStatus.Empty);
            }

            if (_locked)
            {
                return ResultUnsafe(SessionMutationStatus.Locked);
            }

            if (_activeIndex >= _profiles.Length - 1)
            {
                return ResultUnsafe(SessionMutationStatus.BoundaryReached);
            }

            _activeIndex++;
            _generation++;
            return ResultUnsafe(SessionMutationStatus.Succeeded);
        }
    }

    public SessionMutationResult Previous()
    {
        lock (_gate)
        {
            if (_profiles.Length == 0)
            {
                return ResultUnsafe(SessionMutationStatus.Empty);
            }

            if (_locked)
            {
                return ResultUnsafe(SessionMutationStatus.Locked);
            }

            if (_activeIndex <= 0)
            {
                return ResultUnsafe(SessionMutationStatus.BoundaryReached);
            }

            _activeIndex--;
            _generation++;
            return ResultUnsafe(SessionMutationStatus.Succeeded);
        }
    }

    public SessionMutationResult Select(Guid profileId)
    {
        if (profileId == Guid.Empty)
        {
            throw new ArgumentException("Profile identifier cannot be empty.", nameof(profileId));
        }

        lock (_gate)
        {
            if (_profiles.Length == 0)
            {
                return ResultUnsafe(SessionMutationStatus.Empty);
            }

            if (_locked)
            {
                return ResultUnsafe(SessionMutationStatus.Locked);
            }

            int index = Array.FindIndex(
                _profiles,
                profile => profile.ProfileId == profileId);
            if (index < 0)
            {
                return ResultUnsafe(SessionMutationStatus.NotFound);
            }

            if (index != _activeIndex)
            {
                _activeIndex = index;
                _generation++;
            }

            return ResultUnsafe(SessionMutationStatus.Succeeded);
        }
    }

    public SessionMutationResult ClearActive()
    {
        lock (_gate)
        {
            if (_profiles.Length == 0)
            {
                return ResultUnsafe(SessionMutationStatus.Empty);
            }

            var remaining = _profiles.ToList();
            remaining.RemoveAt(_activeIndex);
            _profiles = remaining.ToArray();
            _activeIndex = _profiles.Length == 0
                ? -1
                : Math.Min(_activeIndex, _profiles.Length - 1);
            _locked = false;
            _generation++;
            return ResultUnsafe(SessionMutationStatus.Succeeded);
        }
    }

    /// <summary>
    /// Security clearing always succeeds, even while the active passenger is locked.
    /// </summary>
    public SessionMutationResult Clear()
    {
        lock (_gate)
        {
            _profiles = [];
            _activeIndex = -1;
            _locked = false;
            _generation++;
            return ResultUnsafe(SessionMutationStatus.Succeeded);
        }
    }

    private PassengerProfile? ActiveUnsafe =>
        _activeIndex >= 0 && _activeIndex < _profiles.Length
            ? _profiles[_activeIndex]
            : null;

    private SessionMutationResult ResultUnsafe(SessionMutationStatus status) =>
        new(status, ActiveUnsafe, _activeIndex, _generation);
}
