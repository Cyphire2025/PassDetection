using SmartCopyPaste.Core.Session;

namespace SmartCopyPaste.Core.Tests;

public sealed class PassengerSessionTests
{
    [Fact]
    public void SetProfiles_SelectsFirstAndNavigationNeverWraps()
    {
        PassengerProfile first = Profile("Rahul", "Sharma");
        PassengerProfile second = Profile("Priya", "Verma");
        var session = new PassengerSession();

        SessionMutationResult set = session.SetProfiles(new[] { first, second });
        SessionMutationResult previousAtStart = session.Previous();
        SessionMutationResult next = session.Next();
        SessionMutationResult nextAtEnd = session.Next();

        Assert.Equal(SessionMutationStatus.Succeeded, set.Status);
        Assert.Same(first, set.Active);
        Assert.Equal(SessionMutationStatus.BoundaryReached, previousAtStart.Status);
        Assert.Equal(SessionMutationStatus.Succeeded, next.Status);
        Assert.Same(second, next.Active);
        Assert.Equal(SessionMutationStatus.BoundaryReached, nextAtEnd.Status);
        Assert.Same(second, session.Active);
    }

    [Fact]
    public void Lock_PreventsSwitchAndReplacement()
    {
        PassengerProfile first = Profile("Rahul", "Sharma");
        PassengerProfile second = Profile("Priya", "Verma");
        PassengerProfile replacement = Profile("Aman", "Khan");
        var session = new PassengerSession();
        session.SetProfiles(new[] { first, second });
        session.Locked = true;

        SessionMutationResult next = session.Next();
        SessionMutationResult select = session.Select(second.ProfileId);
        SessionMutationResult replace = session.SetProfiles(new[] { replacement });

        Assert.Equal(SessionMutationStatus.Locked, next.Status);
        Assert.Equal(SessionMutationStatus.Locked, select.Status);
        Assert.Equal(SessionMutationStatus.Locked, replace.Status);
        Assert.Same(first, session.Active);
        Assert.Equal(2, session.Profiles.Count);
    }

    [Fact]
    public void SecurityClear_OverridesLockAndRemovesEveryProfile()
    {
        var session = new PassengerSession();
        session.SetProfiles(new[] { Profile("Rahul", "Sharma") });
        session.Locked = true;

        SessionMutationResult result = session.Clear();

        Assert.Equal(SessionMutationStatus.Succeeded, result.Status);
        Assert.Null(session.Active);
        Assert.Empty(session.Profiles);
        Assert.False(session.Locked);
    }

    [Fact]
    public void ClearActive_SelectsRemainingPassengerWithoutWrapping()
    {
        PassengerProfile first = Profile("Rahul", "Sharma");
        PassengerProfile second = Profile("Priya", "Verma");
        var session = new PassengerSession();
        session.SetProfiles(new[] { first, second });
        session.Next();

        SessionMutationResult result = session.ClearActive();

        Assert.Equal(SessionMutationStatus.Succeeded, result.Status);
        Assert.Single(session.Profiles);
        Assert.Same(first, session.Active);
        Assert.Equal(0, session.ActiveIndex);
    }

    [Fact]
    public void Profile_CopiesInputDictionary()
    {
        var mutable = new Dictionary<string, string>
        {
            ["personal.surname"] = "Sharma",
        };

        PassengerProfile profile = PassengerProfile.Create(mutable);
        mutable["personal.surname"] = "Changed";
        mutable["passport.number"] = "SHOULD-NOT-APPEAR";

        Assert.Equal("Sharma", profile.Fields["personal.surname"]);
        Assert.False(profile.Fields.ContainsKey("passport.number"));
    }

    [Fact]
    public void Session_RejectsDuplicateProfileIdentifiers()
    {
        PassengerProfile original = Profile("Rahul", "Sharma");
        var duplicate = new PassengerProfile(
            original.ProfileId,
            original.Fields,
            "Duplicate");
        var session = new PassengerSession();

        Assert.Throws<ArgumentException>(() =>
            session.SetProfiles(new[] { original, duplicate }));
    }

    [Fact]
    public void Generation_ChangesOnlyOnActualMutation()
    {
        PassengerProfile first = Profile("Rahul", "Sharma");
        var session = new PassengerSession();
        session.SetProfiles(new[] { first });
        long afterSet = session.Generation;

        session.Next();
        long afterBoundary = session.Generation;
        session.Locked = true;
        long afterLock = session.Generation;
        session.Locked = true;

        Assert.Equal(afterSet, afterBoundary);
        Assert.True(afterLock > afterBoundary);
        Assert.Equal(afterLock, session.Generation);
    }

    private static PassengerProfile Profile(string givenName, string surname) =>
        PassengerProfile.Create(
            new Dictionary<string, string>
            {
                ["personal.given_name"] = givenName,
                ["personal.surname"] = surname,
            });
}
