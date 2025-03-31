# ReOrg - Reddit Organizer

* Lists all subscribed subs via

    ```bash
    $ reorg subs
    ```

* And declaratively manages Multireddits (custom feeds):

  * Generate existing custom feeds YAML:
    ```bash
    $ reorg multis genconf
    wrote /Users/george/.config/reorg.yaml
    ```

 * Edit YAML

 * Apply updates:
   ```bash
   $ reorg multis apply
   ```

   With this command the YAML file is the source of truth:
   * If a multireddit doesn't exist, create it and add subs declared under it
     * subscribe to subs too

   * If a multireddit exists online but not in the file, delete it
     * member subs stay subscribed

   * If a multireddit exists, update it with subs declared under in the file

# License

[MIT](LICENSE)

# Copyright

2025 George Kontridze
