{% include 'imports/pipeline.py' %}

{% if framework == 'tensorflow' %}
def build_model(encoders):
    """Builds and compiles the model from scratch.

    # Arguments
        encoders: dict of encoders (used to set size of text/categorical inputs)

    # Returns
        model: A compiled model which can be used to train or predict.
    """

{% if has_text_input %}
{% include 'models/' ~ text_framework ~ '/text.py' %}
{% endif %}

{% for field, field_raw, field_type in nontarget_fields %}
{% if field_type != 'text' %}
{% include 'models/' ~ framework ~ '/' ~ field_type ~ '.py' %}

{% endif %}
{% endfor %}
    # Combine all the inputs into a single layer
    concat = concatenate([
        {% for field, _, field_type in nontarget_fields %}
        {% if field_type == 'text' %}
        {{ field }}_enc{{ ", " if not loop.last }}
        {% elif field_type != 'datetime' %}
        input_{{ field }}{{ ", " if not loop.last }}
        {% else %}
        input_dayofweeks_{{ field }},
        input_hours_{{ field }}{{ ", " if not loop.last and not params['datetime_month']}}
        {% if params['datetime_month'] %}
        ,input_month_{{ field }}{{ ", " if not loop.last }}
        {% endif %}
        {% endif %}
        {% endfor %}
    ], name="concat")

{% include 'models/' ~ framework ~ '/mlp.py' %}

    # Build and compile the model.
    model = Model(inputs=[
        {% for field, _, field_type in nontarget_fields %}
        {% if field_type != 'datetime' and field != target_field %}
        input_{{ field }}{{ ", " if not loop.last }}
        {% elif field != target_field  %}
        input_dayofweeks_{{ field }},
        input_hours_{{ field }}{{ ", " if not loop.last and not params['datetime_month']}}
        {% if params['datetime_month'] %}
        ,input_month_{{ field }}{{ ", " if not loop.last }}
        {% endif %}
        {% endif %}
        {% endfor %}
                ],
                      outputs=[output])

    model.compile(loss={% include 'models/' ~ framework ~ '/loss.py' %},
              optimizer=AdamWOptimizer(learning_rate = {{ params['base_lr'] }},
                                        weight_decay = {{ params['weight_decay'] }}))

    return model
{% endif %}

def build_encoders(df):
    """Builds encoders for fields to be used when
    processing data for the model.

    All encoder specifications are stored in locally
    in /encoders as .json files.

    # Arguments
        df: A pandas DataFrame containing the data.
    """

{% if has_text_input %}
{% include 'encoders/' ~ text_framework ~ '-text.py' %}
{% endif %}

{% for field, field_raw, field_type in nontarget_fields %}
{% if field_type != 'text' %}
{% include 'encoders/' ~ field_type ~ '.py' %}

{% endif %}

{% endfor %}
{% include 'encoders/target.py' %}

def load_encoders():
    """Loads the encoders built during `build_encoders`.

    # Returns
        encoders: A dict of encoder objects/specs.
    """

    encoders = {}

{% if has_text_input %}
{% include 'loaders/' ~ text_framework ~ '-text.py' %}
{% endif %}

{% for field, field_raw, field_type in nontarget_fields %}
{% if field_type != 'text' %}
{% include 'loaders/' ~ field_type ~ '.py' %}

{% endif %}

{% endfor %}
{% include 'loaders/target.py' %}

    return encoders

def process_data(df, encoders, process_target=True):
    """Processes an input DataFrame into a format
    sutable for model prediction.

    This function loads the encoder specifications created in
    `build_encoders`.

    # Arguments
        df: a DataFrame containing the source data
        encoders: a dict of encoders to process the data.
        process_target: boolean to determine if the target should be encoded.

    # Returns
        A tuple: A list containing all the processed fields to be fed
        into the model, and the processed target field.
    """

{% if has_text_input %}
{% include 'processors/' ~ text_framework ~ '-text.py' %}
{% endif %}

{% for field, field_raw, field_type in nontarget_fields %}
{% if field_type != 'text' %}
{% include 'processors/' ~ field_type ~ '.py' %}
{% endif %}

{% endfor %}

    data_enc = [{% for field, _, field_type in nontarget_fields %}
        {% if field_type != 'datetime' %}
        {{ field }}_enc{{ ", " if not loop.last }}
        {% else %}
        {{ field }}_dayofweeks_enc,
        {{ field }}_hour_enc{{ ", " if not loop.last and not params['datetime_month']}}
        {% if params['datetime_month'] %}
        ,{{ field }}_month_enc{{ ", " if not loop.last }}
        {% endif %}
        {% endif %}
        {% endfor %}
        ]

    if process_target:
{% include 'processors/target.py' %}
        return (data_enc, {{ target_field }}_enc)

    return data_enc


def model_predict(df, model, encoders):
    """Generates predictions for a trained model.

    # Arguments
        df: A pandas DataFrame containing the source data.
        model: A compiled model.
        encoders: a dict of encoders to process the data.

    # Returns
        A numpy array of predictions.
    """

    data_enc = process_data(df, encoders, process_target=False)
    {% if framework == 'tensorflow' %}
    {% if problem_type == 'classification' %}
    headers = encoders['{{ target_field }}_encoder'].classes_
    {% elif problem_type == 'binary_classification' %}
    headers = ['probability']
    {% else %}
    headers = ['{{ target_field }}']
    {% endif %}
    predictions =  pd.DataFrame(model.predict(data_enc), columns=headers)

    return predictions
    
    {% endif %}

def model_train(df, model, encoders, args):
    """Trains a model, and saves the data locally.

    # Arguments
        df: A pandas DataFrame containing the source data.
        model: A compiled model.
    """
    
    X, y = process_data(df, encoders)

    {% if problem_type == 'regression' %}
    split = ShuffleSplit(n_splits=1, train_size=args.split, test_size=None, random_state=123)
    {% else %}
    split = StratifiedShuffleSplit(n_splits=1, train_size=args.split, test_size=None, random_state=123)
    {% endif %}

    for train_indices, val_indices in split.split(np.zeros(y.shape[0]), y):
        X_train = [field[train_indices,] for field in X]
        X_val = [field[val_indices,] for field in X]
        y_train = y[train_indices,]
        y_val = y[val_indices,]

    {% if framework == 'tensorflow' %}
    meta = meta_callback(args, X_val, y_val)

    model.fit(X_train, y_train, validation_data=(X_val, y_val),
                epochs=args.epochs,
                callbacks=[meta])
    {% endif %}

{% include 'callbacks/' ~ framework ~ '.py' %}

