I have been looking for a new role. One that fits both my personal preferences such as being [YOUR_PREFERENCES] etc. , as well as ensure my skills are also a good fit for the role. The following is analysis of the role as it fits each of these criteria:

# Preference
## Preference Matches
{{ $('Extract Preferences Response').item.json.preference_matches }}
## Preference Misses
{{ $('Extract Preferences Response').item.json.preference_misses }}
## Potential Preference Matches
{{ $('Extract Preferences Response').item.json.potential_preference_matches }}
### Preferences Rating: {{ $('Extract Preferences Response').item.json.preferences_rating }} 

# Skills
## Skill Matches
- {{ $json.skill_matches.join("\n- ") }}

## Skill Misses
- {{ $json.skill_misses.join("\n- ") }}

## Skill Translations
- {{ $json.skill_translations.join("\n- ") }}

### Skills Rating: {{ $json.skill_rating }}